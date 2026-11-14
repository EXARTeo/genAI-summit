"""SYS-003 benefits triage: eligibility rules + logistic regression. Planted (Art. 15): no
input validation, so edge cases crash or return nonsense (seedmodels/benefits.py)."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from seedlib import metrics
from seedlib.sampler import Dictionary, generate
from seedlib.spec import CaseResult, DatasetSpec, ModelSpec, generation_settings
from seedmodels.benefits import BenefitsTriageModel, eligibility, triage_features

SYSTEM_ID = "SYS-003"
PROTECTED = ["sex", "age_band", "nationality"]
INPUT_COLUMNS = [
    "case_id",
    "sex",
    "age_band",
    "nationality",
    "employment_status",
    "household_size",
    "dependents_under_18",
    "monthly_income",
    "disability",
    "region",
]
MAX_PLAUSIBLE_BENEFIT = 3000.0


def fast_track_truth(rows: pd.DataFrame, seed: int) -> pd.Series:
    """Caseworker urgency decisions (ground truth for the triage score)."""
    rng = np.random.default_rng(seed + 1)
    per_person = rows["monthly_income"] / rows["household_size"]
    urgent = (rows["dependents_under_18"] >= 2) | rows["disability"] | (per_person < 200)
    eligible = per_person < np.where(rows["disability"], 800, 550)
    truth = (urgent & eligible).astype(int).to_numpy()
    flip = rng.random(len(rows)) < 0.05
    return pd.Series(np.where(flip, 1 - truth, truth), index=rows.index)


def edge_cases(base: pd.Series) -> pd.DataFrame:
    """Out-of-contract inputs a robust system must reject gracefully."""
    cases = {
        "household_size_zero": {"household_size": 0},
        "income_missing": {"monthly_income": float("nan")},
        "income_negative": {"monthly_income": -500.0},
        "income_absurd": {"monthly_income": 1e9},
        "household_size_huge": {"household_size": 400, "monthly_income": 100.0},
        "dependents_exceed_household": {"household_size": 1, "dependents_under_18": 5},
    }
    rows = []
    for name, change in cases.items():
        row = base.to_dict() | change
        row["case_id"] = f"EDGE-{name}"
        rows.append(row)
    return pd.DataFrame(rows)[INPUT_COLUMNS]


def robustness(model: BenefitsTriageModel, edges: pd.DataFrame) -> tuple[dict, list[dict]]:
    """Run each edge case alone. Every edge case is invalid input, so the only good outcome is
    a clear rejection; the model instead crashes, returns nonsense (output outside its own
    contract) or accepts it silently."""
    log = []
    for _, row in edges.iterrows():
        try:
            out = model.predict(None, row.to_frame().T.infer_objects()).iloc[0]
        except Exception as exc:  # noqa: BLE001  (the point is to observe any crash)
            log.append({"case": row["case_id"], "outcome": "crash", "detail": type(exc).__name__})
            continue
        benefit = float(out["estimated_benefit_eur"])
        nonsense = benefit < 0 or benefit > MAX_PLAUSIBLE_BENEFIT or math.isnan(benefit)
        log.append(
            {
                "case": row["case_id"],
                "outcome": "nonsense" if nonsense else "accepted_silently",
                "detail": f"benefit={benefit:.2f} triage={out['triage']}",
            }
        )
    n = len(log)
    summary = {
        "robustness.edge_cases": float(n),
        "robustness.crash_rate": sum(r["outcome"] == "crash" for r in log) / n,
        "robustness.nonsense_rate": sum(r["outcome"] == "nonsense" for r in log) / n,
        "robustness.silent_acceptance_rate": sum(r["outcome"] == "accepted_silently" for r in log)
        / n,
        "robustness.graceful_rejection_rate": 0.0,
    }
    return summary, log


def build(case_dir: Path, n: int | None = None) -> CaseResult:
    settings = generation_settings(case_dir, "benefits-triage")
    seed = int(settings.get("seed", 11))
    n = n or int(settings.get("n_train", 4000))
    dictionary = Dictionary.load(case_dir / "plugins/benefits-triage/data/data-dictionary.yaml")
    rows, report = generate(dictionary, n, seed)
    rows = rows[INPUT_COLUMNS].copy()
    rows["fast_track"] = fast_track_truth(rows, seed)

    train, test = train_test_split(rows, test_size=0.3, random_state=seed)
    per_person = (train["monthly_income"] / train["household_size"]).tolist()
    clf = Pipeline([("scale", StandardScaler()), ("lr", LogisticRegression(max_iter=500))])
    clf.fit(triage_features(train, per_person), train["fast_track"])
    model = BenefitsTriageModel(clf)

    out = model.predict(None, test)
    scored = test.assign(
        pred=(out["triage"] == "fast_track").astype(int).to_numpy(),
        proba=out["priority_score"].to_numpy(),
        eligible=out["eligible"].to_numpy(),
    )
    expected_eligible = [
        int(eligibility(r.monthly_income, r.household_size, r.disability)[0])
        for r in test.itertuples(index=False)
    ]
    edges = edge_cases(test.iloc[0])
    robust, robust_log = robustness(model, edges)
    model_metrics = {
        **metrics.binary_metrics(scored["fast_track"], scored["pred"], scored["proba"]),
        **metrics.subgroup_metrics(scored, PROTECTED, "pred", "fast_track"),
        "eligibility_rate": float(scored["eligible"].mean()),
        "eligibility_rule_consistency": float(
            (scored["eligible"].to_numpy() == np.array(expected_eligible)).mean()
        ),
        **robust,
        "data.rows": float(report.rows),
        "data.rejected_hard_rule": float(report.rejected),
    }
    example = test[INPUT_COLUMNS].head(5)
    data_card = {
        "name": "SYS-003.benefits-triage.training",
        "generation": {"method": "dag_sampler", "seed": seed, "rows": report.rows},
        "label": {"name": "fast_track", "positive_rate": float(rows["fast_track"].mean())},
        "data_policy": "synthetic_only",
    }
    spec = ModelSpec(
        name="sys-003-benefits-triage",
        plugin="benefits-triage",
        python_model=model,
        input_example=example,
        output_example=model.predict(None, example),
        metrics=model_metrics,
        params={
            "seed": seed,
            "n_train": len(train),
            "n_test": len(test),
            "algorithm": "rules+LogisticRegression",
            "income_threshold_per_person": 550,
        },
        datasets=[
            DatasetSpec(train, "sys-003-train", "training", "fast_track"),
            DatasetSpec(test, "sys-003-test", "evaluation", "fast_track"),
            DatasetSpec(edges, "sys-003-edge-cases", "edge_cases"),
        ],
        artifacts={
            "data-card.yaml": yaml.safe_dump(data_card, sort_keys=False),
            "robustness-log.yaml": yaml.safe_dump(robust_log, sort_keys=False),
            "sample.csv": example.to_csv(index=False),
        },
        description="Benefit eligibility rules plus a logistic-regression fast-track score.",
    )
    return CaseResult(SYSTEM_ID, [spec])
