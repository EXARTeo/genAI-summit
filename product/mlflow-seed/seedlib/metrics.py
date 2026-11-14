"""Overall and per-subgroup metrics, named for MLflow (``<metric>.<attribute>.<group>``)."""

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score


def _safe_rate(values: pd.Series) -> float:
    return float(values.mean()) if len(values) else float("nan")


def subgroup_metrics(
    frame: pd.DataFrame,
    attributes: list[str],
    pred: str,
    truth: str | None = None,
) -> dict[str, float]:
    """Selection rate, accuracy and TPR per group, plus ratio/gap summaries per attribute.

    ``frame`` holds the protected attributes, the 0/1 prediction column ``pred`` and,
    optionally, the 0/1 ground-truth column ``truth``.
    """
    out: dict[str, float] = {}
    for attr in attributes:
        rates, tprs, accs = {}, {}, {}
        for group, part in frame.groupby(attr):
            rates[group] = _safe_rate(part[pred])
            out[f"selection_rate.{attr}.{group}"] = rates[group]
            out[f"n.{attr}.{group}"] = float(len(part))
            if truth:
                accs[group] = float(accuracy_score(part[truth], part[pred]))
                out[f"accuracy.{attr}.{group}"] = accs[group]
                positives = part[part[truth] == 1]
                if len(positives):
                    tprs[group] = _safe_rate(positives[pred])
                    out[f"tpr.{attr}.{group}"] = tprs[group]
        top = max(rates.values())
        out[f"selection_rate_ratio.{attr}"] = min(rates.values()) / top if top else float("nan")
        if accs:
            out[f"accuracy_gap.{attr}"] = max(accs.values()) - min(accs.values())
        if tprs:
            out[f"equal_opportunity_gap.{attr}"] = max(tprs.values()) - min(tprs.values())
    return out


def binary_metrics(truth: pd.Series, pred: pd.Series, proba: pd.Series | None = None) -> dict:
    out = {"accuracy": float(accuracy_score(truth, pred)), "positive_rate": float(np.mean(pred))}
    if proba is not None and truth.nunique() > 1:
        out["roc_auc"] = float(roc_auc_score(truth, proba))
    return out


def flip_rate(before: pd.Series, after: pd.Series) -> float:
    """Share of rows whose decision changed between a row and its counterfactual twin."""
    return float((before.to_numpy() != after.to_numpy()).mean())
