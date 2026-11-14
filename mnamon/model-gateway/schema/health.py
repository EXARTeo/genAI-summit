from pydantic import BaseModel


class ModelStatus(BaseModel):
    loaded: bool
    version: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    models: dict[str, ModelStatus]
    simulated: list[str]
