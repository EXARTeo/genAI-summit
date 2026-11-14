from fastapi import APIRouter

from schema.predict import PredictRequest, PredictResponse
from utils.predict import predict

router = APIRouter()


@router.post("/{name}/predict", response_model=PredictResponse)
async def predict_model(name: str, body: PredictRequest) -> PredictResponse:
    model, predictions = await predict(name, body.inputs)
    return PredictResponse(predictions=predictions, model=model.name, version=model.version)
