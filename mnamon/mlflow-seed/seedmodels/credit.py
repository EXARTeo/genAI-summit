"""SYS-002 credit scorer (MLflow pyfunc wrapper around a scikit-learn pipeline)."""

import mlflow.pyfunc
import pandas as pd

CREDIT_FEATURES = [
    "monthly_income",
    "employment_years",
    "credit_history_months",
    "debt_to_income",
    "late_payments_12m",
    "loan_amount",
    "loan_term_months",
]


class CreditScorerModel(mlflow.pyfunc.PythonModel):
    """sys-002-credit-scorer: applicant row → ``score`` (P(repaid)) and ``decision``."""

    def __init__(self, pipeline, threshold: float = 0.5):
        self.pipeline = pipeline
        self.threshold = threshold

    def predict(self, context, model_input, params=None):
        frame = pd.DataFrame(model_input)[CREDIT_FEATURES]
        score = self.pipeline.predict_proba(frame)[:, 1].astype(float)
        decision = ["approve" if s >= self.threshold else "decline" for s in score]
        return pd.DataFrame({"score": score, "decision": decision})
