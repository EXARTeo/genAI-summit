from fastapi import APIRouter

from schema.systems import ScreenRequest, ScreenResponse, StageInfo
from utils.predict import screen_sys001

router = APIRouter()


@router.post("/sys-001/screen", response_model=ScreenResponse)
async def screen(body: ScreenRequest) -> ScreenResponse:
    stages, features, predictions = await screen_sys001(body.inputs)
    return ScreenResponse(
        system="sys-001",
        predictions=predictions,
        features=features,
        stages=[StageInfo(model=s.name, version=s.version) for s in stages],
    )
