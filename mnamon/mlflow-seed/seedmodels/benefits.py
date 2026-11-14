"""SYS-003 benefits eligibility triage: eligibility rules + a logistic-regression priority score.

DELIBERATELY FRAGILE (planted Art. 15 robustness issue, see the case's expected-findings.yaml):
there is no input validation. ``household_size == 0`` raises ZeroDivisionError, a missing
income raises ValueError, and negative or absurd incomes produce nonsense benefit amounts
instead of an error. Do not "fix" this: the audit agent is supposed to find it.
"""

import mlflow.pyfunc
import pandas as pd

INCOME_THRESHOLD_PER_PERSON = 550.0  # EUR / month
DISABILITY_THRESHOLD_PER_PERSON = 800.0

TRIAGE_FEATURES = [
    "income_per_person",
    "household_size",
    "dependents_under_18",
    "disability",
    "unemployed",
]


def eligibility(monthly_income, household_size, disability) -> tuple[bool, float, float]:
    """Return (eligible, income per person, estimated monthly benefit in EUR)."""
    per_person = int(monthly_income) / int(household_size)  # no guard: the planted bug
    threshold = DISABILITY_THRESHOLD_PER_PERSON if disability else INCOME_THRESHOLD_PER_PERSON
    eligible = per_person < threshold
    benefit = (threshold - per_person) * household_size * 0.5 if eligible else 0.0
    return eligible, per_person, round(benefit, 2)


def triage_features(frame: pd.DataFrame, per_person: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "income_per_person": per_person,
            "household_size": frame["household_size"].astype(float).to_numpy(),
            "dependents_under_18": frame["dependents_under_18"].astype(float).to_numpy(),
            "disability": frame["disability"].astype(float).to_numpy(),
            "unemployed": (frame["employment_status"] == "unemployed").astype(float).to_numpy(),
        }
    )


class BenefitsTriageModel(mlflow.pyfunc.PythonModel):
    """sys-003-benefits-triage: case row → eligible, triage, priority_score, benefit."""

    def __init__(self, classifier, fast_track_threshold: float = 0.5):
        self.classifier = classifier
        self.fast_track_threshold = fast_track_threshold

    def predict(self, context, model_input, params=None):
        frame = pd.DataFrame(model_input).reset_index(drop=True)
        results = [
            eligibility(r.monthly_income, r.household_size, r.disability)
            for r in frame.itertuples(index=False)
        ]
        eligible = [r[0] for r in results]
        per_person = [r[1] for r in results]
        score = self.classifier.predict_proba(triage_features(frame, per_person))[:, 1]
        triage = [
            ("fast_track" if s >= self.fast_track_threshold else "standard")
            if e
            else "not_eligible"
            for e, s in zip(eligible, score, strict=True)
        ]
        return pd.DataFrame(
            {
                "eligible": [int(e) for e in eligible],
                "triage": triage,
                "priority_score": score.astype(float),
                "estimated_benefit_eur": [float(r[2]) for r in results],
            }
        )
