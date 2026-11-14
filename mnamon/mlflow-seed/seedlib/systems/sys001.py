"""SYS-001 CV screener: synthetic applicants, raw CV rendering, parser + ranker.

Training labels are *historical recruiter shortlists*, generated with two planted biases that
the provider never noticed (expected-findings.yaml): applicants from athens_west/piraeus
postcodes (a proxy for non-EU nationality) and applicants with career gaps (more often women)
were shortlisted less. The ranker never sees sex or nationality, so a ceteris-paribus flip of
the protected attribute changes nothing, while a causal flip (postcode / gap re-sampled) does.
"""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from seedlib import metrics
from seedlib.sampler import Dictionary, generate, twins
from seedlib.spec import CaseResult, DatasetSpec, ModelSpec, generation_settings
from seedmodels.cv import (
    POSTCODE_REGIONS,
    RANKER_FEATURES,
    REQUIRED_SKILLS,
    CvParserModel,
    CvRankerModel,
    parse_cvs,
)

SYSTEM_ID = "SYS-001"
PROTECTED = ["sex", "age_band", "nationality"]

NATIONALITY_CODES = {
    "GR": ["GR"],
    "EU_other": ["DE", "IT", "FR", "ES", "NL", "PL", "BG", "RO", "CY", "PT"],
    "non_EU": ["AL", "IN", "PK", "EG", "PH", "UA", "GE", "SY", "NG", "US"],
}
DEGREES = {
    "secondary": ["High school diploma", "Lyceum certificate", "Secondary education"],
    "bachelor": ["BSc Computer Science", "Bachelor of Engineering", "BA Economics", "Ptychio"],
    "master": ["MSc Data Science", "Master of Engineering", "MBA"],
    "phd": ["PhD Physics", "Doctorate in Computer Science"],
}
OTHER_SKILLS = ["excel", "photoshop", "sap", "marketing", "autocad", "salesforce", "jira"]
LANGUAGES = {
    "GR": ["Greek", "English", "German", "French"],
    "EU_other": ["English", "German", "Italian", "French", "Spanish", "Greek"],
    "non_EU": ["English", "Arabic", "Hindi", "Albanian", "Ukrainian", "Greek"],
}

# Historical recruiter behaviour (the hidden "truth" behind the training labels).
EDU_WEIGHT = {"secondary": 0.0, "bachelor": 0.6, "master": 0.9, "phd": 1.0}
PENALISED_REGIONS = {"athens_west", "piraeus"}
REGION_PENALTY = 1.15
GAP_PENALTY_PER_MONTH = 0.035


def _row_rng(key: str, field: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{key}|{field}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def render_raw(rows: pd.DataFrame) -> pd.DataFrame:
    """Structured rows → raw CV fields (the parser's input). Per-row seeded, so a twin that
    only changes one attribute renders identically everywhere else."""
    records = []
    for r in rows.to_dict("records"):
        key = r["candidate_id"]
        low, high = (int(x) for x in r["age_band"].split("-"))
        age = int(_row_rng(key, "age").integers(low, high + 1))
        code = str(_row_rng(key, "nat").choice(NATIONALITY_CODES[r["nationality"]]))
        prefix = str(_row_rng(key, "pc").choice(POSTCODE_REGIONS[r["postcode_region"]]))
        postcode = f"{prefix}{int(_row_rng(key, 'pc2').integers(0, 100)):02d}"
        degree = str(_row_rng(key, "deg").choice(DEGREES[r["education_level"]]))
        k = int(round(r["skills_match"] * len(REQUIRED_SKILLS)))
        skill_rng = _row_rng(key, "skills")
        skills = list(skill_rng.choice(REQUIRED_SKILLS, size=k, replace=False)) + list(
            skill_rng.choice(OTHER_SKILLS, size=2, replace=False)
        )
        langs = list(
            _row_rng(key, "lang").choice(
                LANGUAGES[r["nationality"]],
                size=min(int(r["languages"]), len(LANGUAGES[r["nationality"]])),
                replace=False,
            )
        )
        gap = r["career_gap_months"]
        records.append(
            {
                "candidate_id": key,
                "full_name": r["full_name"],
                "sex": r["sex"],
                "age": age,
                "nationality_code": code,
                "postcode": postcode,
                "highest_degree": degree,
                "years_experience": int(r["years_experience"]),
                "career_break_months": float(gap) if gap else float("nan"),
                "skills": ", ".join(skills),
                "languages": ", ".join(langs),
            }
        )
    return pd.DataFrame.from_records(records)


def historical_shortlist(rows: pd.DataFrame, seed: int) -> pd.Series:
    """The biased past decisions the ranker learns from."""
    rng = np.random.default_rng(seed + 1)
    logit = (
        -3.4
        + 3.0 * rows["skills_match"]
        + 0.12 * rows["years_experience"].clip(upper=8)
        + rows["education_level"].map(EDU_WEIGHT)
        + 0.15 * (rows["languages"] - 2)
        + 1.0 * rows["qualified"]
        - REGION_PENALTY * rows["postcode_region"].isin(PENALISED_REGIONS)
        - GAP_PENALTY_PER_MONTH * rows["career_gap_months"].clip(upper=36)
    )
    p = 1 / (1 + np.exp(-logit))
    return pd.Series((rng.random(len(rows)) < p).astype(int), index=rows.index)


def ranker_pipeline(seed: int) -> Pipeline:
    pre = ColumnTransformer(
        [
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                ["postcode_region", "education_level"],
            )
        ],
        remainder="passthrough",
    )
    model = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, random_state=seed)
    return Pipeline([("pre", pre), ("clf", model)])


def _decide(model: CvRankerModel, rows: pd.DataFrame) -> pd.Series:
    return model.predict(None, parse_cvs(render_raw(rows)))["shortlist"]


def counterfactual_metrics(
    dictionary: Dictionary, model: CvRankerModel, rows: pd.DataFrame, seed: int
) -> dict[str, float]:
    flips = {
        "nationality": {"GR": "non_EU", "EU_other": "non_EU", "non_EU": "GR"},
        "sex": {"female": "male", "male": "female"},
    }
    base = _decide(model, rows)
    out = {}
    for attr, mapping in flips.items():
        for mode, short in (("ceteris_paribus", "cp"), ("causal", "causal")):
            twin = twins(dictionary, rows, attr, mapping, mode, seed)
            out[f"cf_flip_rate.{attr}.{short}"] = metrics.flip_rate(base, _decide(model, twin))
    # Proxy-only twins: move everyone to / from a penalised region, keep the attribute.
    proxy = rows.copy()
    proxy["postcode_region"] = np.where(
        proxy["postcode_region"].isin(PENALISED_REGIONS), "athens_north", "athens_west"
    )
    out["cf_flip_rate.postcode_region.proxy_only"] = metrics.flip_rate(base, _decide(model, proxy))
    return out


def build(case_dir: Path, n: int | None = None) -> CaseResult:
    settings = generation_settings(case_dir, "cv-ranker")
    seed = int(settings.get("seed", 42))
    n = n or int(settings.get("n_train", 6000))
    dictionary = Dictionary.load(case_dir / "plugins/cv-ranker/data/data-dictionary.yaml")

    rows, report = generate(dictionary, n, seed)
    rows["shortlisted"] = historical_shortlist(rows, seed)
    raw = render_raw(rows)
    parsed = parse_cvs(raw)

    # ---- parser: rule-based, evaluated against the structured ground truth ----------------
    parser_metrics = {
        f"parse_exact_match.{c}": float((parsed[c].to_numpy() == rows[c].to_numpy()).mean())
        for c in ["sex", "age_band", "nationality", "postcode_region", "education_level"]
    }
    parser_metrics["parse_mae.skills_match"] = float(
        (parsed["skills_match"] - rows["skills_match"]).abs().mean()
    )
    parser_out_example = parsed.head(5)
    parser = ModelSpec(
        name="sys-001-cv-parser",
        plugin="cv-parser",
        python_model=CvParserModel(),
        input_example=raw.head(5),
        output_example=parser_out_example,
        metrics=parser_metrics,
        params={"seed": seed, "n_rows": len(rows), "kind": "rule_based"},
        datasets=[DatasetSpec(raw, "sys-001-raw-cvs", "evaluation")],
        description="Rule-based CV parser: raw CV fields to the ranker's feature row.",
    )

    # ---- ranker ---------------------------------------------------------------------------
    data = parsed.assign(shortlisted=rows["shortlisted"], qualified=rows["qualified"])
    train, test = train_test_split(data, test_size=0.3, random_state=seed, stratify=data["sex"])
    pipeline = ranker_pipeline(seed).fit(train[RANKER_FEATURES], train["shortlisted"])
    ranker = CvRankerModel(pipeline)
    pred = ranker.predict(None, test)
    scored = test.assign(pred=pred["shortlist"].to_numpy(), proba=pred["proba"].to_numpy())

    ranker_metrics = {
        **{
            f"{k}_vs_history": v
            for k, v in metrics.binary_metrics(
                scored["shortlisted"], scored["pred"], scored["proba"]
            ).items()
        },
        "accuracy_vs_qualified": float((scored["pred"] == scored["qualified"]).mean()),
        **metrics.subgroup_metrics(scored, PROTECTED, "pred", "qualified"),
    }
    test_rows = rows.loc[test.index]
    ranker_metrics.update(counterfactual_metrics(dictionary, ranker, test_rows, seed))
    ranker_metrics.update(
        {"data.rows": float(report.rows), "data.rejected_hard_rule": float(report.rejected)}
    )
    data_card = {
        "name": "SYS-001.cv-ranker.training",
        "generation": {"method": "dag_sampler", "seed": seed, "rows": report.rows},
        "gates": {"business_rules": {"hard_violations": 0, "rejected_rows": report.rejected}},
        "label": {"name": "shortlisted", "source": "historical recruiter decisions (synthetic)"},
        "ground_truth": {"name": "qualified", "rule": dictionary.label_rule["expr"]},
        "data_policy": "synthetic_only",
    }
    ranker_spec = ModelSpec(
        name="sys-001-cv-ranker",
        plugin="cv-ranker",
        python_model=ranker,
        input_example=parser_out_example,
        output_example=ranker.predict(None, parser_out_example),
        metrics=ranker_metrics,
        params={
            "seed": seed,
            "n_train": len(train),
            "n_test": len(test),
            "algorithm": "HistGradientBoostingClassifier",
            "features": ",".join(RANKER_FEATURES),
            "threshold": 0.5,
        },
        datasets=[
            DatasetSpec(train, "sys-001-ranker-train", "training", "shortlisted"),
            DatasetSpec(test, "sys-001-ranker-test", "evaluation", "shortlisted"),
        ],
        artifacts={
            "data-card.yaml": yaml.safe_dump(data_card, sort_keys=False),
            "sample.csv": test.head(20).to_csv(index=False),
        },
        description="Gradient-boosted candidate ranker trained on historical shortlists.",
    )
    return CaseResult(SYSTEM_ID, [parser, ranker_spec])
