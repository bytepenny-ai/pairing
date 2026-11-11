"""The Forecast page: runs a time-series model (TimesFM) on the user's numbers through the active engine."""

import asyncio
import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.model_catalog import CATALOG
from app.quant_label import QuantLabel
from app.schemas.forecast import (
    ForecastCatalogEntry,
    ForecastDefaultSetting,
    ForecastLimits,
    ForecastModelCatalogResponse,
    ForecastModelsResponse,
    ForecastRunRequest,
    ForecastRunResponse,
    ForecastStreamEvent,
    SeriesForecast,
)
from app.services.default_model_settings import DefaultModelSettings
from app.services.engines.registry import registry
from app.services.forecast_limits_setting import ForecastLimitsSetting

# Seconds between "waiting" lines: keeps proxies (the ring's balancer cuts 300 s of silence) and the page's
# timer alive during a long forecast.
HEARTBEAT_SECONDS = 10.0


class ForecastUnavailableError(Exception):
    """The request can't run here (engine or model); a 400 for the caller."""


class ForecastService:
    def __init__(self, db: AsyncSession) -> None:
        self._settings = DefaultModelSettings(db)
        self._limits = ForecastLimitsSetting(db)

    @staticmethod
    def engine_supports() -> bool:
        return registry.active().capabilities.forecast

    async def models(self) -> ForecastModelsResponse:
        supported = self.engine_supports()
        models = await self._settings.installed_forecasters() if supported else []
        return ForecastModelsResponse(
            engine_supports=supported,
            models=models,
            limits=await self._limits.get(),
            default_model=await self._settings.forecast(models) if models else None,
        )

    async def default_setting(self) -> ForecastDefaultSetting:
        supported = self.engine_supports()
        installed = await self._settings.installed_forecasters() if supported else []
        model = await self._settings.forecast(installed) if installed else None
        return ForecastDefaultSetting(model=model, installed=installed, engine_supports=supported)

    async def set_default(self, model: str) -> ForecastDefaultSetting:
        if model not in await self._settings.installed_forecasters():
            raise ForecastUnavailableError(f"{model} is not an installed forecasting model.")
        await self._settings.set_forecast(model)
        return await self.default_setting()

    async def prepare(self, request: ForecastRunRequest) -> ForecastLimits:
        """Checks before the reply starts streaming (so they answer 400); returns the limits to run under."""
        if not self.engine_supports():
            raise ForecastUnavailableError("Forecasting needs the Matricxon engine.")
        if request.model not in await self._settings.installed_forecasters():
            raise ForecastUnavailableError(f"{request.model} is not an installed forecasting model.")
        return await self._limits.get()

    @staticmethod
    async def stream(request: ForecastRunRequest, limits: ForecastLimits) -> AsyncIterator[str]:
        """NDJSON: a "waiting" line every HEARTBEAT_SECONDS, then "result" or "error". Leaving early (the page's
        Cancel) cancels the engine call."""
        engine = registry.active()
        limit = limits.time_limit_seconds or None
        task = asyncio.ensure_future(engine.forecast(request.model, request.series, request.horizon, limit))
        started = time.monotonic()

        def line(kind: str, **fields: object) -> str:
            event = ForecastStreamEvent(type=kind, elapsed_seconds=round(time.monotonic() - started, 1), **fields)
            return event.model_dump_json(exclude_none=True) + "\n"

        try:
            while not task.done():
                await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
                if task.done():
                    break
                if limit and time.monotonic() - started > limit:
                    yield line("error", detail=f"The forecast took longer than the {limit} s limit.")
                    return
                yield line("waiting")
            try:
                raw = task.result()
            except Exception as exc:  # noqa: BLE001 - the page always gets an answer line
                yield line("error", detail=str(exc) or type(exc).__name__)
                return
            forecasts = [SeriesForecast(**item) for item in raw]
            result = ForecastRunResponse(model=request.model, horizon=request.horizon, forecasts=forecasts)
            yield line("result", result=result)
        finally:
            if not task.done():
                task.cancel()

    async def catalog(self) -> ForecastModelCatalogResponse:
        """Admin settings > Models > Forecasting models: the curated list with install state."""
        supported = self.engine_supports()
        installed = set(await self._settings.installed_forecasters()) if supported else set()
        entries = [
            ForecastCatalogEntry(
                family=entry.family,
                vendor=entry.vendor,
                tag=entry.tag,
                parameter_size=entry.parameter_size,
                context_length=entry.context_length,
                download_gb=entry.download_gb,
                min_ram_gb=entry.min_ram_gb,
                installed=entry.tag in installed,
                quantization=QuantLabel.from_tag(entry.tag) or next(iter(entry.quantizations or []), None),
            )
            for entry in CATALOG.forecast_models
        ]
        return ForecastModelCatalogResponse(engine_supports=supported, entries=entries)
