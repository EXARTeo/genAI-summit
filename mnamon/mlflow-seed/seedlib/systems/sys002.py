"""SYS-002 credit scorer: nearly clean. Planted: applicants aged 18-25 have thin credit files,
so their outcomes are noisier and the model is less accurate for them (accuracy gap)."""

from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split

from seedlib import metrics
from seedlib.sampler import Dictionary, generate
from seedlib.spec import CaseResult, DatasetSpec, ModelSpec, generation_settings
from seedmodels.credit import CREDIT_FEATURES, CreditScorerModel

SYSTEM_ID = "SYS-002"
PROTECTED = ["sex", "age_band"]
THIN_FILE_NOISE = {"18-25": 0.10}  # share of outcomes the features cannot explain
BASE_NOISE = 0.03


def repaid_outcome(rows: pd.DataFrame, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed + 1)
    installment_ratio = rows["loan_amount"] / rows["loan_term_months"] / rows["monthly_income"]
    logit = (
        3.0
        + 1.2 * np.log(rows["monthly_income"] / 1500)
        - 4.5 * rows["debt_to_income"]
        - 0.9 * rows["late_payments_12m"]
        + 0.004 * rows["credit_history_months"].clip(upper=120)
        - 5.0 * installment_ratio
    )
    repaid = (1 / (1 + np.exp(-logit)) >= 0.5).astype(int)
    noise = rows["age_band"].map(THIN_FILE_NOISE).fillna(BASE_NOISE)
    flip = rng.random(len(rows)) < noise
    return pd.Series(np.where(flip, 1 - repaid, repaid), index=rows.index)


def build(case_dir: Path, n: int | None = None) -> CaseResult:
    settings = generation_settings(case_dir, "credit-scorer")
    seed = int(settings.get("seed", 7))
    n = n or int(settings.get("n_train", 6000))
    dictionary = Dictionary.load(case_dir / "plugins/credit-scorer/data/data-dictionary.yaml")
    rows, report = generate(dictionary, n, seed)
    rows["repaid"] = repaid_outcome(rows, seed)

    train, test = train_test_split(
        rows, test_size=0.3, random_state=seed, stratify=rows["age_band"]
    )
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06, random_state=seed)
    clf.fit(train[CREDIT_FEATURES], train["repaid"])
    model = CreditScorerModel(clf)
    pred = model.predict(None, test)
    scored = test.assign(
        pred=(pred["decision"] == "approve").astype(int).to_numpy(), proba=pred["score"].to_numpy()
    )
    model_metrics = {
        **metrics.binary_metrics(scored["repaid"], scored["pred"], scored["proba"]),
        **metrics.subgroup_metrics(scored, PROTECTED, "pred", "repaid"),
        "data.rows": float(report.rows),
        "data.rejected_hard_rule": float(report.rejected),
    }
    young = scored["age_band"] == "18-25"
    model_metrics["accuracy_gap.age_band.18-25_vs_rest"] = float(
        (scored.loc[~young, "pred"] == scored.loc[~young, "repaid"]).mean()
        - (scored.loc[young, "pred"] == scored.loc[young, "repaid"]).mean()
    )
    columns = ["applicant_id", "sex", "age_band", *CREDIT_FEATURES]
    example = test[columns].head(5)
    data_card = {
        "name": "SYS-002.credit-scorer.training",
        "generation": {"method": "dag_sampler", "seed": seed, "rows": report.rows},
        "label": {"name": "repaid", "positive_rate": float(rows["repaid"].mean())},
        "data_policy": "synthetic_only",
    }
    spec = ModelSpec(
        name="sys-002-credit-scorer",
        plugin="credit-scorer",
        python_model=model,
        input_example=example,
        output_example=model.predict(None, example),
        metrics=model_metrics,
        params={
            "seed": seed,
            "n_train": len(train),
            "n_test": len(test),
            "algorithm": "HistGradientBoostingClassifier",
            "features": ",".join(CREDIT_FEATURES),
            "threshold": 0.5,
        },
        datasets=[
            DatasetSpec(train[[*columns, "repaid"]], "sys-002-train", "training", "repaid"),
            DatasetSpec(test[[*columns, "repaid"]], "sys-002-test", "evaluation", "repaid"),
        ],
        artifacts={
            "data-card.yaml": yaml.safe_dump(data_card, sort_keys=False),
            "sample.csv": test[columns].head(20).to_csv(index=False),
        },
        description="Gradient-boosted probability of repayment for consumer loans.",
    )
    return CaseResult(SYSTEM_ID, [spec])
