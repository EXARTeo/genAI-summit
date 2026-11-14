"""Run one command in a fresh per-call workdir, under limits.

Layout of a call's workdir (deleted afterwards)::

    <work_root>/<random>/
        input/    the request's input/<rel> files
        output/   the request's output/<rel> files; whatever the command leaves
                  here (new or changed) comes back in the response
        tmp/      TMPDIR/HOME for the command

Limits (Linux; on other platforms only the timeout, output and disk caps hold):

* **time**: wall clock ``timeout_seconds`` → the whole process group is killed
  (``killed_reason="timeout"``); CPU time is capped at the same number (RLIMIT_CPU).
* **memory**: RLIMIT_AS; a ``MemoryError`` or an allocator kill → ``memory``.
* **output**: each stream is captured up to ``max_output_bytes``; printing more
  kills the command → ``output_limit`` (and ``truncated``).
* **disk**: RLIMIT_FSIZE per file, and the workdir total is measured after the
  run; over ``max_disk_bytes`` → ``disk_limit`` and no files come back.
* **processes**: the container's cgroup ``pids_limit`` (compose). Not RLIMIT_NPROC: it
  counts every process of the uid on the host, so it breaks fork under load.

Network isolation is the container's job (compose: ``sandbox_net`` + an internal
network that reaches only ``mlflow`` and ``model-gateway``).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

if os.name == "posix":
    import resource

from core.logging import get_logger
from core.settings import settings
from schema.exec import ExecFile, ExecRequest, ExecResult, ReturnedFile

logger = get_logger(__name__)

IS_POSIX = os.name == "posix"
_TRANSFER_ROOTS = ("input", "output")
_MEMORY_MARKERS = ("MemoryError", "Cannot allocate memory", "std::bad_alloc", "Unable to allocate")


class InvalidFiles(ValueError):
    """The request's files break the contract (path, encoding or caps)."""


@dataclass
class _Capture:
    """One stream, read in a thread, capped."""

    limit: int
    data: bytearray = field(default_factory=bytearray)
    overflow: bool = False

    def pump(self, stream, on_overflow) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            room = self.limit - len(self.data)
            if room > 0:
                self.data.extend(chunk[:room])
            if len(chunk) > room and not self.overflow:
                self.overflow = True
                on_overflow()
        stream.close()

    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


def _safe_rel(path: str) -> PurePosixPath:
    """``input/<rel>`` or ``output/<rel>``, normalised; anything else is refused."""
    if "\\" in path or "\x00" in path:
        raise InvalidFiles(f"Invalid file path: {path!r}")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in ("..", "") for part in pure.parts) or len(pure.parts) < 2:
        raise InvalidFiles(f"Invalid file path: {path!r}")
    if pure.parts[0] not in _TRANSFER_ROOTS:
        raise InvalidFiles(f"Files must be under input/ or output/: {path!r}")
    return pure


def write_inputs(workdir: Path, files: list[ExecFile]) -> dict[str, str]:
    """Write the request's files; returns ``{rel: sha256}`` of what went in."""
    cfg = settings.exec
    if len(files) > cfg.max_files:
        raise InvalidFiles(f"Too many files (max {cfg.max_files}).")
    total = 0
    hashes: dict[str, str] = {}
    for item in files:
        rel = _safe_rel(item.path)
        try:
            data = base64.b64decode(item.content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidFiles(f"File {item.path!r} is not valid base64.") from exc
        total += len(data)
        if total > cfg.max_transfer_bytes:
            raise InvalidFiles("Files are over the transfer limit.")
        target = workdir.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[str(rel)] = hashlib.sha256(data).hexdigest()
    return hashes


def _dir_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            with contextlib.suppress(OSError):
                total += (Path(dirpath) / name).lstat().st_size
    return total


def collect_outputs(workdir: Path, sent: dict[str, str]) -> tuple[list[ReturnedFile], bool]:
    """Every regular file under ``output/`` that is new or changed, within the caps."""
    cfg = settings.exec
    out_root = workdir / "output"
    files: list[ReturnedFile] = []
    truncated = False
    total = 0
    if not out_root.is_dir():
        return files, False
    for path in sorted(out_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue  # a symlink could point anywhere in the box
        rel = "output/" + path.relative_to(out_root).as_posix()
        data = path.read_bytes()
        if sent.get(rel) == hashlib.sha256(data).hexdigest():
            continue
        if len(files) >= cfg.max_files or total + len(data) > cfg.max_transfer_bytes:
            truncated = True
            continue
        total += len(data)
        files.append(
            ReturnedFile(
                path=rel, content_b64=base64.b64encode(data).decode("ascii"), size=len(data)
            )
        )
    return files, truncated


def _child_env(workdir: Path) -> dict[str, str]:
    tmp = str(workdir / "tmp")
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": tmp,
        "TMPDIR": tmp,
        "TEMP": tmp,
        "TMP": tmp,
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",
        "SANDBOX_WORKDIR": str(workdir),
        # BLAS/OpenMP/Arrow pools size themselves to the host's cores; under the
        # address-space cap that many threads cannot start (EAGAIN).
        "OMP_NUM_THREADS": str(settings.exec.threads),
        "OPENBLAS_NUM_THREADS": str(settings.exec.threads),
        "MKL_NUM_THREADS": str(settings.exec.threads),
        "NUMEXPR_NUM_THREADS": str(settings.exec.threads),
    }
    if not IS_POSIX:
        for name in ("SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR"):
            if name in os.environ:
                env[name] = os.environ[name]
    for name in settings.exec.passthrough_names:
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def _limits(timeout: int):  # noqa: ANN202 - a preexec_fn
    cfg = settings.exec

    def apply() -> None:
        def cap(which: int, value: int) -> None:
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(which, (value, value))

        cap(resource.RLIMIT_AS, cfg.memory_mb * 1024 * 1024)
        cap(resource.RLIMIT_CPU, timeout + 1)
        cap(resource.RLIMIT_FSIZE, cfg.max_disk_bytes)
        cap(resource.RLIMIT_CORE, 0)

    return apply


def _kill(proc: subprocess.Popen) -> None:
    try:
        if IS_POSIX:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(  # noqa: S603
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],  # noqa: S607
                capture_output=True,
                check=False,
            )
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _signal_of(returncode: int | None) -> int | None:
    """The signal that ended the command: ``-N`` from Popen, or ``128 + N`` when the
    shell reports a killed child."""
    if not IS_POSIX or returncode is None:
        return None
    if returncode < 0:
        return -returncode
    if 128 < returncode < 160:
        return returncode - 128
    return None


def _killed_reason(
    *, timed_out: bool, overflow: bool, returncode: int | None, stderr: str, disk_over: bool
) -> str | None:
    if timed_out:
        return "timeout"
    if overflow:
        return "output_limit"
    sig = _signal_of(returncode)
    tail = stderr[-4000:]
    if disk_over or sig == getattr(signal, "SIGXFSZ", 25) or "File size limit exceeded" in tail:
        return "disk_limit"
    if sig == getattr(signal, "SIGXCPU", 24):
        return "timeout"
    if returncode not in (0, None) and any(m in tail for m in _MEMORY_MARKERS):
        return "memory"
    if sig == signal.SIGKILL:
        return "memory"  # the kernel's (or cgroup's) OOM kill
    return None


def run_command(request: ExecRequest) -> ExecResult:
    """Blocking: one call, start to finish. Raises :class:`InvalidFiles`."""
    cfg = settings.exec
    timeout = request.timeout_seconds or cfg.default_timeout_seconds
    cfg.work_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="exec-", dir=cfg.work_root))
    started = time.monotonic()
    try:
        for name in ("input", "output", "tmp"):
            (workdir / name).mkdir()
        sent = write_inputs(workdir, request.files)
        cwd = workdir / request.workdir if request.workdir not in ("", ".") else workdir
        if IS_POSIX:
            argv: list[str] | str = ["/bin/sh", "-c", request.command]
            kwargs = {"start_new_session": True, "preexec_fn": _limits(timeout)}
        else:
            argv = request.command
            kwargs = {"shell": True, "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        try:
            proc = subprocess.Popen(  # noqa: S603 - running the command is the point
                argv,
                cwd=cwd,
                env=_child_env(workdir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )
        except OSError as exc:
            logger.error(
                "exec_spawn_failed", "Could not start the command", error=type(exc).__name__
            )
            return ExecResult(
                exit_code=None,
                stderr="The sandbox could not start the command.",
                duration_ms=int((time.monotonic() - started) * 1000),
                killed_reason="error",
            )

        out, err = _Capture(cfg.max_output_bytes), _Capture(cfg.max_output_bytes)
        threads = [
            threading.Thread(target=out.pump, args=(proc.stdout, lambda: _kill(proc)), daemon=True),
            threading.Thread(target=err.pump, args=(proc.stderr, lambda: _kill(proc)), daemon=True),
        ]
        for t in threads:
            t.start()
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            proc.wait()
        for t in threads:
            t.join(timeout=5)

        disk_over = _dir_size(workdir) > cfg.max_disk_bytes
        stderr = err.text()
        reason = _killed_reason(
            timed_out=timed_out,
            overflow=out.overflow or err.overflow,
            returncode=proc.returncode,
            stderr=stderr,
            disk_over=disk_over,
        )
        files, files_truncated = (
            ([], False) if reason == "disk_limit" else collect_outputs(workdir, sent)
        )
        exit_code = None if timed_out else proc.returncode
        return ExecResult(
            exit_code=exit_code,
            stdout=out.text(),
            stderr=stderr,
            truncated=out.overflow or err.overflow,
            duration_ms=int((time.monotonic() - started) * 1000),
            killed_reason=reason,
            files=files,
            files_truncated=files_truncated,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def runtime_info() -> dict[str, str]:
    return {"python": sys.version.split()[0], "platform": sys.platform}
