"""``synthkit`` command line (run inside the sandbox through ``execute``).

    synthkit profile   --plugin plugin.yaml --dictionary data-dictionary.yaml
                       [--sample sample.csv] [--model-uri URI | --url URL | --model-pickle F]
                       [--seed 0] [--n-probe 256] --out model-profile.json
    synthkit scenarios-check --scenarios scenarios.yaml --plugin plugin.yaml
                       --dictionary data-dictionary.yaml [--profile model-profile.json]
                       --out-dir DIR
    synthkit generate  --spec generation-spec.yaml --seed N --out-dir DIR
                       [--format csv|parquet|both]
    synthkit analyze   --dataset DIR/dataset.parquet --spec generation-spec.yaml
                       [--profile model-profile.json] [--sample sample.csv] --out-dir DIR
    synthkit run-tests --plan test-plan.yaml --target plugin.yaml [--data DIR]
                       [--card system-card.yaml] [--dictionary data-dictionary.yaml]
                       [--model-uri URI | --url URL | --model-pickle F] [--no-mlflow]
                       [--seed 0] [--predictions predictions.parquet] --out DIR
    synthkit run-inference --data DIR --target plugin.yaml [--plan test-plan.yaml]
                       [--dictionary data-dictionary.yaml]
                       [--model-uri URI | --url URL | --model-pickle F] [--seed 0]
                       [--no-mlflow] --out DIR      → predictions.parquet + run.json
    synthkit metrics   = run-tests with --predictions required (replay, no model call)

Each command prints a short summary on stdout; exit code 2 = bad input,
3 = the model could not be reached, 1 = a gate failed (analyze) or a test
failed (run-tests).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from modelaccess.runlog import RunLogger

from synthkit.analyze import load_dataset, run_analysis, write_analysis
from synthkit.generate import generate
from synthkit.inference import run_inference
from synthkit.profile import run_profile, write_profile
from synthkit.runtests import CHAT_TEMPLATES, chat_client, load_plan, run_tests, summary
from synthkit.scenarios import check_scenarios, write_report
from synthkit.spec import Dictionary, SpecError, load_spec, load_yaml, read_sample
from synthkit.target import TargetError, load_target


def _profile(args: argparse.Namespace) -> int:
    plugin = load_yaml(args.plugin) or {}
    dictionary = Dictionary.load(args.dictionary)
    sample = read_sample(args.sample, dictionary.fields) if args.sample else None
    target = load_target(
        plugin, model_uri=args.model_uri, model_pickle=args.model_pickle, url=args.url
    )
    profile = run_profile(
        target,
        dictionary,
        plugin,
        seed=args.seed,
        n_probe=args.n_probe,
        n_oat=args.n_oat,
        sample=sample,
    )
    write_profile(profile, args.out)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "inputs": profile["signature"]["inputs"],
                "positive_rate": profile["output"]["positive_rate"],
                "top_features": profile["sensitivity_ranking"][:5],
                "notes": profile["notes"],
                "calls": profile["calls"],
            },
            indent=2,
        )
    )
    return 0


def _scenarios(args: argparse.Namespace) -> int:
    doc = load_yaml(args.scenarios) or {}
    plugin = load_yaml(args.plugin) or {}
    dictionary = Dictionary.load(args.dictionary)
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8")) if args.profile else None
    report = check_scenarios(doc, dictionary, plugin, profile)
    write_report(report, args.out_dir)
    print(json.dumps({"status": report["status"], "missing": report["missing"]}, indent=2))
    return 0


def _generate(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    card = generate(spec, args.seed, args.out_dir, args.format)
    print(
        json.dumps(
            {
                "out_dir": str(args.out_dir),
                "dataset_id": card["dataset_id"],
                "content_sha256": card["content_sha256"],
                "composition": card["composition"]["by_test"],
                "rules": card["rules"],
            },
            indent=2,
            default=str,
        )
    )
    return 0


def _analyze(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    frame = load_dataset(args.dataset)
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8")) if args.profile else None
    sample = read_sample(args.sample, spec.dictionary.fields) if args.sample else None
    analysis = run_analysis(frame, spec, seed=args.seed, profile=profile, sample=sample)
    write_analysis(analysis, args.out_dir, spec.name)
    print(
        json.dumps(
            {
                "overall": analysis["overall"],
                "gates": {k: v["status"] for k, v in analysis["gates"].items()},
                "twin_validity": analysis["twin_validity"],
            },
            indent=2,
        )
    )
    return 1 if analysis["overall"] == "fail" else 0


def _default_dictionary(args: argparse.Namespace, plugin: dict) -> Path | None:
    """``--dictionary``, else the plugin's ``io.input_schema`` next to plugin.yaml."""
    if args.dictionary is not None:
        return args.dictionary
    schema = (plugin.get("io") or {}).get("input_schema")
    candidate = Path(args.target).parent / schema if isinstance(schema, str) else None
    return candidate if candidate and candidate.exists() else None


def _run_inference(args: argparse.Namespace) -> int:
    plugin = load_yaml(args.target) or {}
    plan = load_plan(args.plan) if args.plan else {}
    system = plan.get("system") or plugin.get("system") or "unknown"
    logger = RunLogger(f"compliance/{system}", enabled=False if args.no_mlflow else None)
    run = run_inference(
        args.data,
        args.out,
        plugin_path=args.target,
        plan_path=args.plan,
        dictionary_path=_default_dictionary(args, plugin),
        target_factory=lambda: load_target(
            plugin, model_uri=args.model_uri, model_pickle=args.model_pickle, url=args.url
        ),
        run_logger=logger,
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "predictions": run["predictions"],
                "dataset_sha256": run["dataset"]["sha256"],
                "model": {k: run["model"][k] for k in ("uri_or_url", "kind", "version")},
                "mlflow_run_id": run["mlflow_run_id"],
            },
            indent=2,
            default=str,
        )
    )
    return 0


def _run_tests(args: argparse.Namespace) -> int:
    plugin = load_yaml(args.target) or {}
    plan = load_plan(args.plan)
    chat_only = all(t["template"] in CHAT_TEMPLATES for t in plan["tests"])
    is_chat = (plugin.get("access") or {}).get("type") == "llm_chat"
    if args.predictions is not None and not Path(args.predictions).is_file():
        raise SpecError(f"--predictions {args.predictions} does not exist")

    def target_factory():
        return load_target(
            plugin, model_uri=args.model_uri, model_pickle=args.model_pickle, url=args.url
        )

    system = plan.get("system") or plugin.get("system") or "unknown"
    logger = RunLogger(f"compliance/{system}", enabled=False if args.no_mlflow else None)
    dictionary = args.dictionary if chat_only else _default_dictionary(args, plugin)
    live_chat = is_chat and args.predictions is None
    report = run_tests(
        args.plan,
        args.target,
        args.data,
        args.out,
        card_path=args.card,
        dictionary_path=dictionary,
        target_factory=None if is_chat else target_factory,
        chat_factory=(lambda: chat_client(plugin)) if live_chat else None,
        run_logger=logger,
        seed=args.seed,
        predictions_path=args.predictions,
    )
    print(summary(report))
    return 1 if report["summary"]["fail"] or report["summary"]["error"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthkit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profile", help="probe the model and write model-profile.json")
    p.add_argument("--plugin", type=Path, required=True)
    p.add_argument("--dictionary", type=Path, required=True)
    p.add_argument("--sample", type=Path)
    p.add_argument("--model-uri")
    p.add_argument("--model-pickle", type=Path)
    p.add_argument("--url")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--n-probe", type=int, default=256)
    p.add_argument("--n-oat", type=int, default=48)
    p.add_argument("--out", type=Path, default=Path("model-profile.json"))
    p.set_defaults(fn=_profile)

    s = sub.add_parser("scenarios-check", help="sanity-check scenarios.yaml")
    s.add_argument("--scenarios", type=Path, required=True)
    s.add_argument("--plugin", type=Path, required=True)
    s.add_argument("--dictionary", type=Path, required=True)
    s.add_argument("--profile", type=Path)
    s.add_argument("--out-dir", type=Path, default=Path("."))
    s.set_defaults(fn=_scenarios)

    g = sub.add_parser("generate", help="spec + seed → dataset + DataCard.yaml")
    g.add_argument("--spec", type=Path, required=True)
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--out-dir", type=Path, default=Path("."))
    g.add_argument("--format", choices=["csv", "parquet", "both"], default="both")
    g.set_defaults(fn=_generate)

    a = sub.add_parser("analyze", help="five gates + twins → dataset-analysis.json/.md")
    a.add_argument("--dataset", type=Path, required=True)
    a.add_argument("--spec", type=Path, required=True)
    a.add_argument("--profile", type=Path)
    a.add_argument("--sample", type=Path)
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--out-dir", type=Path, default=Path("."))
    a.set_defaults(fn=_analyze)

    i = sub.add_parser(
        "run-inference", help="call the model only → predictions.parquet + run.json (no metrics)"
    )
    i.add_argument("--data", type=Path, required=True, help="a synthkit generate output dir")
    i.add_argument("--target", type=Path, required=True, help="the plugin.yaml under test")
    i.add_argument("--plan", type=Path, help="test-plan.yaml (perturbed copies, audit ids)")
    i.add_argument("--dictionary", type=Path)
    i.add_argument("--model-uri")
    i.add_argument("--model-pickle", type=Path)
    i.add_argument("--url")
    i.add_argument("--seed", type=int, default=0)
    i.add_argument("--no-mlflow", action="store_true", help="do not log the MLflow run")
    i.add_argument("--out", type=Path, default=Path("inference"))
    i.set_defaults(fn=_run_inference)

    for name, help_text, replay_required in (
        ("run-tests", "test plan → test-results.json/.md (+ MLflow runs)", False),
        ("metrics", "run-tests replaying --predictions (no model call)", True),
    ):
        r = sub.add_parser(name, help=help_text)
        r.add_argument("--plan", type=Path, required=True)
        r.add_argument("--target", type=Path, required=True, help="the plugin.yaml under test")
        r.add_argument("--data", type=Path, help="a synthkit generate output dir")
        r.add_argument("--card", type=Path, help="system-card.yaml (thresholds)")
        r.add_argument("--dictionary", type=Path)
        r.add_argument(
            "--predictions",
            type=Path,
            required=replay_required,
            help="run-inference's predictions.parquet: replay it, call no model",
        )
        r.add_argument("--model-uri")
        r.add_argument("--model-pickle", type=Path)
        r.add_argument("--url")
        r.add_argument("--seed", type=int, default=0)
        r.add_argument("--no-mlflow", action="store_true", help="do not log MLflow runs")
        r.add_argument("--out", type=Path, default=Path("results"))
        r.set_defaults(fn=_run_tests)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except SpecError as exc:
        print(f"synthkit: invalid input: {exc}", file=sys.stderr)
        return 2
    except TargetError as exc:
        print(f"synthkit: model unreachable or unreadable: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
