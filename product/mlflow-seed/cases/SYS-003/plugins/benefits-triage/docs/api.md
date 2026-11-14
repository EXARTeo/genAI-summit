# sys-003-benefits-triage: API

## MLflow

```python
model = mlflow.pyfunc.load_model("models:/sys-003-benefits-triage@champion")
model.predict(df)  # -> DataFrame[eligible, triage, priority_score, estimated_benefit_eur]
```

## REST through the model gateway

`POST http://model-gateway:8000/v1/models/sys-003-benefits-triage/predict`,
`Authorization: Bearer <token>` (host: `http://localhost:8200`).

```json
{"inputs": [{
  "case_id": "CASE-000515", "sex": "male", "age_band": "65-90", "nationality": "GR",
  "employment_status": "retired", "household_size": 2, "dependents_under_18": 1,
  "monthly_income": 645.32, "disability": false, "region": "other"
}]}
```

Response:

```json
{"predictions": [{"eligible": 1, "triage": "standard", "priority_score": 0.30,
  "estimated_benefit_eur": 227.5}], "model": "sys-003-benefits-triage", "version": "1"}
```

## Signature

| Column | Type |
| --- | --- |
| case_id, sex, age_band, nationality, employment_status, region | string |
| household_size, dependents_under_18 | long |
| monthly_income | double |
| disability | boolean |

Errors: the gateway returns 422 for schema violations (missing column, wrong type). Values inside
the schema types are passed to the model unchecked.
