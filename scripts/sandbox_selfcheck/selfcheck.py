"""Self-check: run profile → generate → analyze → run-tests for the seed systems INSIDE the
real sandbox container (POST /v1/exec, the same path the agents use) and compare the
measured numbers with the answer keys.

    python scripts/sandbox_selfcheck/selfcheck.py [--cases SYS-001,SYS-004] [--out DIR]

Needs the stack up (sandbox_runner, mlflow, mlflow-seed done, model-gateway) and a Python
with numpy/pandas/scikit-learn/pyyaml (the sandbox venv) for SYS-002's labelled holdout.
The answer keys are read here, on the host, and are never sent into the sandbox.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CASES = REPO / "product" / "mlflow-seed" / "cases"
COMPOSE = ["docker", "compose", "--env-file", ".env.example", "-f", "product/docker-compose.yaml"]
PLUGINS = {
    "SYS-001": "cv-ranker",
    "SYS-002": "credit-scorer",
    "SYS-003": "benefits-triage",
    "SYS-004": "support-chatbot",
}
SEEDS = {"SYS-001": 42, "SYS-002": 7, "SYS-003": 11, "SYS-004": 4}

# Posts the request on stdin to the runner from inside its own container.
INNER = """
import json, os, sys, time, urllib.request
for _ in range(60):  # wait for the runner after a restart
    try:
        urllib.request.urlopen("http://localhost:8090/health", timeout=2)
        break
    except OSError:
        time.sleep(1)
req = urllib.request.Request(
    "http://localhost:8090/v1/exec", data=sys.stdin.buffer.read(), method="POST",
    headers={"Content-Type": "application/json",
             "X-Internal-Proxy-Secret": os.environ.get("TRUSTED_PROXY_SECRET", "")})
sys.stdout.write(urllib.request.urlopen(req, timeout=1000).read().decode())
"""

# Answer-key metric → run-tests metric.
RENAME = {
    "cf_flip_rate.nationality.cp": "cf_flip_rate.nationality.attribute_only",
    "cf_flip_rate.sex.cp": "cf_flip_rate.sex.attribute_only",
    "cf_flip_rate.postcode_region.proxy_only": "cf_flip_rate.nationality.proxy_only",
    "accuracy_gap.age_band.18-25_vs_rest": "accuracy_gap.age_band.18-25_vs_rest",
}


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def sys002_holdout() -> Path:
    """The provider's labelled evaluation split (same generator, seed and split as the seed
    job). Stands in for the holdout an auditor asks the provider for (Art. 10(3))."""
    sys.path.insert(0, str(REPO / "product" / "mlflow-seed"))
    from sklearn.model_selection import train_test_split  # noqa: PLC0415

    from seedlib.sampler import Dictionary, generate  # noqa: PLC0415
    from seedlib.systems.sys002 import repaid_outcome  # noqa: PLC0415

    case = CASES / "SYS-002"
    seed = SEEDS["SYS-002"]
    rows, _ = generate(
        Dictionary.load(case / "plugins/credit-scorer/data/data-dictionary.yaml"), 6000, seed
    )
    rows["repaid"] = repaid_outcome(rows, seed)
    _, test = train_test_split(rows, test_size=0.3, random_state=seed, stratify=rows["age_band"])
    out = HERE / "out" / "SYS-002-eval.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    test.to_csv(out, index=False)
    return out


def build_request(system: str) -> dict:
    plugin_dir = CASES / system / "plugins" / PLUGINS[system]
    files = {
        "plugin.yaml": plugin_dir / "plugin.yaml",
        "data-dictionary.yaml": plugin_dir / "data" / "data-dictionary.yaml",
        "system-card.yaml": CASES / system / "system-card.yaml",
        "test-plan.yaml": HERE / system / "test-plan.yaml",
    }
    spec = HERE / system / "generation-spec.yaml"
    if spec.exists():
        files["generation-spec.yaml"] = spec
    if system == "SYS-002":
        files["eval.csv"] = sys002_holdout()
    seed = SEEDS[system]
    steps = []
    if spec.exists():
        if "model_profile" in spec.read_text(encoding="utf-8"):
            steps.append(
                "synthkit profile --plugin ../input/plugin.yaml "
                "--dictionary ../input/data-dictionary.yaml --n-probe 192 "
                "--out ../input/model-profile.json > profile.log"
            )
        steps.append(
            f"synthkit generate --spec ../input/generation-spec.yaml --seed {seed} "
            "--out-dir data --format parquet > generate.log"
        )
        steps.append(
            "(synthkit analyze --dataset data/dataset.parquet "
            "--spec ../input/generation-spec.yaml --out-dir data > analyze.log || true)"
        )
    data = "--data data " if spec.exists() else ""
    steps.append(
        "synthkit run-tests --plan ../input/test-plan.yaml --target ../input/plugin.yaml "
        f"{data}--seed {seed} --out results"
    )
    command = " && ".join(steps)
    return {
        "user_id": "selfcheck",
        "agent_slug": "selfcheck",
        "conversation_id": system.lower(),
        "command": command,
        "timeout_seconds": 900,
        "workdir": "output",
        "files": [{"path": f"input/{name}", "content_b64": b64(p)} for name, p in files.items()],
    }


def run_in_sandbox(request: dict) -> dict:
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*COMPOSE, "exec", "-T", "sandbox_runner", "python", "-c", INNER],
        input=json.dumps(request).encode(),
        capture_output=True,
        cwd=REPO,
        timeout=1100,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"docker compose exec failed: {proc.stderr.decode()[-2000:]}")
    return json.loads(proc.stdout)


def compare(system: str, results: dict) -> list[str]:
    key = yaml.safe_load(
        (CASES / system / "_answer-key" / "expected-findings.yaml").read_text(encoding="utf-8")
    )
    by_metric = {r["metric"]: r for r in results["results"] if r["metric"]}
    lines = []
    for finding in key.get("findings", []):
        metrics = {finding["metric"]: finding.get("expected", {})}
        metrics.update(finding.get("supporting_metrics") or {})
        for name, exp in metrics.items():
            if name == "documentation":
                lines.append(f"  {finding['id']} documentation gap: out of scope for run-tests")
                continue
            ours = RENAME.get(name, name.removeprefix("robustness."))
            got = by_metric.get(ours)
            if got is None:
                lines.append(f"  {finding['id']} {name}: NOT MEASURED")
                continue
            lo, hi = (exp.get("range") or [None, None])[:2]
            value = got["value"]
            in_range = (
                ""
                if lo is None or value is None
                else (" in range" if lo <= value <= hi else " OUT")
            )
            lines.append(
                f"  {finding['id']} {name}: expected ~{exp.get('approx')} {exp.get('range', '')}"
                f" -> got {value} ci={got['ci95']} [{got['status']}]{in_range}"
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="SYS-001,SYS-002,SYS-003,SYS-004")
    parser.add_argument("--out", type=Path, default=HERE / "out")
    args = parser.parse_args()
    if shutil.which("docker") is None:
        os.environ["PATH"] += os.pathsep + r"C:\Program Files\Docker\Docker\resources\bin"
    report = []
    for system in args.cases.split(","):
        print(f"== {system}: running in the sandbox ...", flush=True)
        resp = run_in_sandbox(build_request(system))
        out = args.out / system
        out.mkdir(parents=True, exist_ok=True)
        for f in resp.get("files") or []:
            dest = out / f["path"].removeprefix("output/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(f["content_b64"]))
        (out / "exec.log").write_text(
            f"exit={resp.get('exit_code')} killed={resp.get('killed_reason')} "
            f"ms={resp.get('duration_ms')}\n--- stdout\n{resp.get('stdout')}\n"
            f"--- stderr\n{resp.get('stderr')}\n",
            encoding="utf-8",
        )
        results_path = out / "results" / "test-results.json"
        if not results_path.exists():
            print(f"  no results (exit {resp.get('exit_code')}): see {out / 'exec.log'}")
            print((resp.get("stderr") or "")[-1500:])
            continue
        results = json.loads(results_path.read_text(encoding="utf-8"))
        lines = [
            f"{system}: {results['summary']} mlflow={results['mlflow']['enabled']} "
            f"dataset={results['dataset_id']}",
            *compare(system, results),
        ]
        print("\n".join(lines), flush=True)
        report.extend(lines)
    (args.out / "selfcheck.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
