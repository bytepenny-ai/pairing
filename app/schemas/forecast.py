"""The Forecast page (routers/forecast.py) and Admin settings > Models > Forecasting models."""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
# Matricxon reads at most the latest 16384 values; more is cut here instead of sent.
MAX_SERIES_LENGTH = 16384
MAX_HORIZON = 128  # TimesFM 2.5's limit


class ForecastRunRequest(BaseModel):
    model: str = Field(min_length=1)
    # One or more series, oldest value first.
    series: list[list[FiniteFloat]] = Field(min_length=1, max_length=20)
    horizon: int = Field(ge=1, le=MAX_HORIZON)

    @field_validator("series")
    @classmethod
    def _check_lengths(cls, series: list[list[float]]) -> list[list[float]]:
        if any(len(values) < 2 for values in series):
            raise ValueError("each series needs at least 2 values")
        return [values[-MAX_SERIES_LENGTH:] for values in series]


class SeriesForecast(BaseModel):
    point: list[float]  # the median
    mean: list[float]
    quantiles: dict[str, list[float]]  # "0.1" ... "0.9"


class ForecastRunResponse(BaseModel):
    model: str
    horizon: int
    forecasts: list[SeriesForecast]


class ForecastLimits(BaseModel):
    """Ring-wide limits (services/forecast_limits_setting.py)."""

    # The largest file the Forecast page reads (it is read in the browser, never uploaded).
    max_file_mb: int = Field(default=1024, ge=1, le=1_048_576)
    # How long one forecast may run; 0 = no limit.
    time_limit_seconds: int = Field(default=0, ge=0, le=86_400)


class ForecastModelsResponse(BaseModel):
    # False when the active engine can't forecast (only Matricxon can).
    engine_supports: bool
    models: list[str]
    max_horizon: int = MAX_HORIZON
    # The latest values per series a forecast reads; the page keeps only these from a big file.
    max_series_length: int = MAX_SERIES_LENGTH
    limits: ForecastLimits = ForecastLimits()
    # Preselected on the page (Admin settings > Models > Default models).
    default_model: str | None = None


class ForecastDefaultSetting(BaseModel):
    model: str | None
    installed: list[str]
    engine_supports: bool


class ForecastDefaultUpdate(BaseModel):
    model: str = Field(min_length=1)


class ForecastStreamEvent(BaseModel):
    """One NDJSON line of POST /api/forecast: "waiting" heartbeats, then "result" or "error"."""

    type: str
    elapsed_seconds: float
    result: ForecastRunResponse | None = None
    detail: str | None = None


class ForecastCatalogEntry(BaseModel):
    family: str
    vendor: str
    tag: str
    parameter_size: str
    context_length: int | None
    download_gb: float | None
    min_ram_gb: float
    installed: bool
    # Shown as a badge (e.g. "Q8_0").
    quantization: str | None = None


class ForecastModelCatalogResponse(BaseModel):
    engine_supports: bool
    entries: list[ForecastCatalogEntry]
