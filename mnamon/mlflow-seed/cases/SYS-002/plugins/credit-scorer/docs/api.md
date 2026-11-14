# sys-002-credit-scorer: API

## MLflow

```python
model = mlflow.pyfunc.load_model("models:/sys-002-credit-scorer@champion")
model.predict(df)  # -> DataFrame[score, decision]
```

## REST through the model gateway

`POST http://model-gateway:8000/v1/models/sys-002-credit-scorer/predict`,
`Authorization: Bearer <token>` (host: `http://localhost:8200`).

```json
{"inputs": [{
  "applicant_id": "APP-000105", "sex": "male", "age_band": "26-35", "monthly_income": 1836.69,
  "employment_years": 9, "credit_history_months": 119, "debt_to_income": 0.078,
  "late_payments_12m": 0, "loan_amount": 1493.45, "loan_term_months": 36
}]}
```

Response:

```json
{"predictions": [{"score": 0.99, "decision": "approve"}], "model": "sys-002-credit-scorer", "version": "1"}
```

## Signature

| Column | Type |
| --- | --- |
| applicant_id, sex, age_band | string |
| monthly_income, debt_to_income, loan_amount | double |
| employment_years, credit_history_months, late_payments_12m, loan_term_months | long |
