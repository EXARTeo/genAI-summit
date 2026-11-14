"""Try discovery on a local system folder (no backend needed)::

python -m harness.tools.public_datasets search --system-dir <case> --out-dir <dir>
python -m harness.tools.public_datasets fetch --candidates <dir>/<plugin>/dataset-candidates.json
    --id openml:31 --approved-by <who> --out-dir <system folder copy>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.tools.public_datasets.context import load_contexts, read_system_dir
from harness.tools.public_datasets.fetch import LocalStore, fetch_from_result
from harness.tools.public_datasets.search import search_public_datasets, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="public_datasets")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--system-dir", type=Path, required=True)
    s.add_argument("--plugin")
    s.add_argument("--top", type=int, default=8)
    s.add_argument("--out-dir", type=Path, required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--candidates", type=Path, required=True)
    f.add_argument("--id", required=True)
    f.add_argument("--approved-by", required=True)
    f.add_argument("--max-rows", type=int, default=5000)
    f.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "search":
        contexts = load_contexts(read_system_dir(args.system_dir))
        if args.plugin:
            contexts = [c for c in contexts if c.plugin == args.plugin]
        summary = []
        for ctx in contexts:
            result = search_public_datasets(ctx, top=args.top)
            write_report(result, args.out_dir / ctx.plugin)
            summary.append(
                {
                    "plugin": ctx.plugin,
                    "sources": result["sources"],
                    "top": [(c["id"], c["name"], c["score"]) for c in result["candidates"][:5]],
                }
            )
        print(json.dumps(summary, indent=2))
        return 0
    result = json.loads(args.candidates.read_text(encoding="utf-8"))
    slug = next(c["slug"] for c in result["candidates"] if c["id"] == args.id)
    out = fetch_from_result(
        result,
        args.id,
        store=LocalStore(args.out_dir, slug),
        approved_by=args.approved_by,
        max_rows=args.max_rows,
    )
    print(json.dumps({k: v for k, v in out.items() if k != "files"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
