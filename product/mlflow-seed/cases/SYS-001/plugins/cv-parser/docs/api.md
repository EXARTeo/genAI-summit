# sys-001-cv-parser: API

## MLflow

```python
model = mlflow.pyfunc.load_model("models:/sys-001-cv-parser@champion")
features = model.predict(raw_df)  # columns = the ranker's input columns
```

## REST through the model gateway

`POST http://model-gateway:8000/v1/models/sys-001-cv-parser/predict`, `Authorization: Bearer <token>`.

```json
{"inputs": [{
  "candidate_id": "CAND-000001", "full_name": "Jonas Weber", "sex": "male", "age": 35,
  "nationality_code": "ES", "postcode": "10529", "highest_degree": "Master of Engineering",
  "years_experience": 12, "career_break_months": null,
  "skills": "docker, git, pytorch, linux, photoshop, marketing", "languages": "English, Greek"
}]}
```

Response:

```json
{"predictions": [{"candidate_id": "CAND-000001", "sex": "male", "age_band": "35-44",
  "nationality": "EU_other", "postcode_region": "athens_centre", "education_level": "master",
  "years_experience": 12, "career_gap_months": 0, "skills_match": 0.5, "languages": 2}],
 "model": "sys-001-cv-parser", "version": "1"}
```

`career_break_months: null` means no break. End to end with the ranker:
`POST http://model-gateway:8000/v1/systems/sys-001/screen`.

## Signature

`age`, `years_experience`: long; `career_break_months`: double (nullable); everything else string.
