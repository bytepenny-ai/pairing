"""The Forecast page's API (any logged-in user) and Admin settings > Models > Forecasting models."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.schemas.forecast import (
    ForecastDefaultSetting,
    ForecastDefaultUpdate,
    ForecastLimits,
    ForecastModelCatalogResponse,
    ForecastModelsResponse,
    ForecastRunRequest,
)
from app.services.auth_service import get_current_user, require_admin
from app.services.forecast_limits_setting import ForecastLimitsSetting
from app.services.forecast_service import ForecastService, ForecastUnavailableError
from app.services.inference_client import InferenceError

router = APIRouter(tags=["forecast"])


@router.get("/api/forecast/models", response_model=ForecastModelsResponse)
async def get_forecast_models(
    db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> ForecastModelsResponse:
    try:
        return await ForecastService(db).models()
    except InferenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/forecast", response_class=StreamingResponse)
async def run_forecast(
    body: ForecastRunRequest, db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> StreamingResponse:
    """Streams NDJSON ForecastStreamEvent lines: heartbeats while the model works, then the result or an error."""
    try:
        limits = await ForecastService(db).prepare(body)
    except ForecastUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InferenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamingResponse(ForecastService.stream(body, limits), media_type="application/x-ndjson")


@router.get("/api/settings/forecast-model-catalog", response_model=ForecastModelCatalogResponse)
async def get_forecast_model_catalog(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ForecastModelCatalogResponse:
    try:
        return await ForecastService(db).catalog()
    except InferenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/settings/forecast-limits", response_model=ForecastLimits)
async def get_forecast_limits(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ForecastLimits:
    return await ForecastLimitsSetting(db).get()


@router.put("/api/settings/forecast-limits", response_model=ForecastLimits)
async def set_forecast_limits(
    body: ForecastLimits, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ForecastLimits:
    return await ForecastLimitsSetting(db).set(body)


@router.get("/api/settings/forecast-model", response_model=ForecastDefaultSetting)
async def get_default_forecast_model(
    db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ForecastDefaultSetting:
    """Admin settings > Models > Default models > Default forecasting model."""
    try:
        return await ForecastService(db).default_setting()
    except InferenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.put("/api/settings/forecast-model", response_model=ForecastDefaultSetting)
async def set_default_forecast_model(
    body: ForecastDefaultUpdate, db: AsyncSession = Depends(get_db), _admin: User = Depends(require_admin)
) -> ForecastDefaultSetting:
    try:
        return await ForecastService(db).set_default(body.model)
    except ForecastUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InferenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
