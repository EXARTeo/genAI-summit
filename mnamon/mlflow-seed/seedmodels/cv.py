"""SYS-001 CV screener: rule-based parser + ranker wrapper (MLflow pyfunc models).

Shipped inside each logged model via ``code_paths``, so ``mlflow.pyfunc.load_model`` works
without this repo. Depends only on pandas, numpy, scikit-learn and mlflow.
"""

import re

import mlflow.pyfunc
import pandas as pd

AGE_BANDS = [(18, 24, "18-24"), (25, 34, "25-34"), (35, 44, "35-44"), (45, 54, "45-54")]
OLDEST_BAND = "55-67"

EU_CODES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "HR", "HU", "IE", "IT",
    "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}  # fmt: skip

POSTCODE_REGIONS = {
    "athens_centre": ["104", "105", "106", "113", "114", "117"],
    "athens_north": ["145", "146", "151", "152", "154"],
    "athens_west": ["121", "122", "123", "131", "132"],
    "piraeus": ["185", "186", "187"],
    "thessaloniki": ["542", "543", "544", "546", "551"],
    "other": ["261", "301", "382", "412", "491", "712", "731"],
}
_PREFIX_TO_REGION = {p: region for region, ps in POSTCODE_REGIONS.items() for p in ps}

# What the engineering role asks for; skills_match = share of these found in the CV.
REQUIRED_SKILLS = ["python", "sql", "docker", "kubernetes", "aws", "git", "linux", "pytorch"]

PARSER_OUTPUT = [
    "candidate_id",
    "sex",
    "age_band",
    "nationality",
    "postcode_region",
    "education_level",
    "years_experience",
    "career_gap_months",
    "skills_match",
    "languages",
]

# The ranker never sees sex, age_band or nationality directly.
RANKER_FEATURES = [
    "postcode_region",
    "education_level",
    "years_experience",
    "career_gap_months",
    "skills_match",
    "languages",
]


def age_band(age: object) -> str:
    try:
        value = int(float(age))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "unknown"
    for low, high, label in AGE_BANDS:
        if low <= value <= high:
            return label
    return OLDEST_BAND if value >= 55 else "unknown"


def nationality_group(code: object) -> str:
    text = str(code or "").strip().upper()
    if text == "GR":
        return "GR"
    return "EU_other" if text in EU_CODES else "non_EU"


def postcode_region(postcode: object) -> str:
    digits = re.sub(r"\D", "", str(postcode or ""))
    return _PREFIX_TO_REGION.get(digits[:3], "other")


def education_level(degree: object) -> str:
    text = str(degree or "").lower()
    if re.search(r"\bph\.?d\b|doctor", text):
        return "phd"
    if re.search(r"\bm\.?sc\b|master|\bmba\b|\bmeng\b", text):
        return "master"
    if re.search(r"\bb\.?sc\b|bachelor|\bba\b|\bbeng\b|ptychio", text):
        return "bachelor"
    return "secondary"


def _items(text: object) -> list[str]:
    return [s.strip().lower() for s in str(text or "").split(",") if s.strip()]


def skills_match(skills: object) -> float:
    found = set(_items(skills)) & set(REQUIRED_SKILLS)
    return round(len(found) / len(REQUIRED_SKILLS), 4)


def _int_or_zero(value: object) -> int:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return 0 if number != number else max(0, int(round(number)))  # NaN -> 0


def parse_cvs(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw CV fields to the ranker's feature row (deterministic, rule-based)."""
    out = pd.DataFrame(index=raw.index)
    out["candidate_id"] = raw["candidate_id"].astype(str)
    out["sex"] = raw["sex"].astype(str).str.lower()
    out["age_band"] = raw["age"].map(age_band)
    out["nationality"] = raw["nationality_code"].map(nationality_group)
    out["postcode_region"] = raw["postcode"].map(postcode_region)
    out["education_level"] = raw["highest_degree"].map(education_level)
    out["years_experience"] = raw["years_experience"].map(_int_or_zero).astype("int64")
    out["career_gap_months"] = raw["career_break_months"].map(_int_or_zero).astype("int64")
    out["skills_match"] = raw["skills"].map(skills_match).astype(float)
    out["languages"] = raw["languages"].map(lambda t: max(1, len(_items(t)))).astype("int64")
    return out[PARSER_OUTPUT]


class CvParserModel(mlflow.pyfunc.PythonModel):
    """sys-001-cv-parser: raw CV fields → structured features (PARSER_OUTPUT)."""

    def predict(self, context, model_input, params=None):
        return parse_cvs(pd.DataFrame(model_input))


class CvRankerModel(mlflow.pyfunc.PythonModel):
    """sys-001-cv-ranker: parser output → ``shortlist`` (0/1) and ``proba``."""

    def __init__(self, pipeline, threshold: float = 0.5):
        self.pipeline = pipeline
        self.threshold = threshold

    def predict(self, context, model_input, params=None):
        frame = pd.DataFrame(model_input)[RANKER_FEATURES]
        proba = self.pipeline.predict_proba(frame)[:, 1]
        return pd.DataFrame(
            {"shortlist": (proba >= self.threshold).astype("int64"), "proba": proba.astype(float)}
        )
