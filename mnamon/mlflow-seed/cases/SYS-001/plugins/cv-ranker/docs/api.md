# sys-001-cv-ranker: API

## MLflow (sandbox, `access.type: mlflow_model`)

```python
import mlflow, pandas as pd

model = mlflow.pyfunc.load_model("models:/sys-001-cv-ranker@champion")
model.predict(pd.DataFrame([row]))  # -> DataFrame[shortlist, proba]
```

## REST through the model gateway

`POST http://model-gateway:8000/v1/models/sys-001-cv-ranker/predict` with
`Authorization: Bearer <token>` (from the host: `http://localhost:8200`).

Request (every column of the signature, no extra fields):

```json
{"inputs": [{
  "candidate_id": "CAND-000001", "sex": "male", "age_band": "35-44", "nationality": "EU_other",
  "postcode_region": "athens_centre", "education_level": "master", "years_experience": 12,
  "career_gap_months": 0, "skills_match": 0.5, "languages": 2
}]}
```

Response:

```json
{"predictions": [{"shortlist": 1, "proba": 0.83}], "model": "sys-001-cv-ranker", "version": "1"}
```

Whole pipeline (raw CV → parser → ranker): `POST http://model-gateway:8000/v1/systems/sys-001/screen`
with the parser's raw fields; the response adds `features` (the parser output) and `stages`.

## Signature

| Column | Type |
| --- | --- |
| candidate_id, sex, age_band, nationality, postcode_region, education_level | string |
| years_experience, career_gap_months, languages | long |
| skills_match | double |

Errors: 422 on a missing or extra column or a wrong type; 503 while MLflow has no `champion` yet.
