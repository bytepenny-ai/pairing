"""The Forecast page's API (routers/forecast.py, services/forecast_service.py) and its curated catalog."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.model_catalog import CATALOG
from app.routers import forecast as forecast_router
from app.schemas.forecast import MAX_SERIES_LENGTH, ForecastDefaultUpdate, ForecastLimits, ForecastRunRequest
from app.schemas.memory_pins import PinInstalled
from app.services import forecast_service
from app.services.default_model_settings import DefaultModelSettings

FORECAST = {"point": [3.0, 4.0], "mean": [3.1, 4.1], "quantiles": {"0.1": [2.0, 3.0], "0.9": [4.0, 5.0]}}


class _Engine:
    """A stand-in active engine; `forecast` capability and replies set per test."""

    error_types = (RuntimeError,)

    def __init__(self, supports: bool = True, fails: bool = False, delay: float = 0.0) -> None:
        self.capabilities = SimpleNamespace(forecast=supports)
        self._fails = fails
        self._delay = delay
        self.calls: list[tuple] = []
        self.cancelled = False

    async def forecast(self, model, series, horizon, timeout_seconds=None) -> list[dict]:
        self.calls.append((model, series, horizon, timeout_seconds))
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self._fails:
            raise RuntimeError("Matricxon is down")
        return [FORECAST for _ in series]


@pytest.fixture
def engine(monkeypatch) -> _Engine:
    active = _Engine()
    monkeypatch.setattr(forecast_service.registry, "active", lambda: active)

    async def installed(capability: str) -> list[str]:
        return ["tfm:q8", "tfm:f32"] if capability == "forecast" else []

    monkeypatch.setattr(DefaultModelSettings, "_installed_with_capability", staticmethod(installed))
    return active


def _request(**extra) -> ForecastRunRequest:
    return ForecastRunRequest(**{"model": "tfm:q8", "series": [[1.0, 2.0, 3.0]], "horizon": 2, **extra})


@pytest.mark.asyncio
async def test_models_lists_installed_forecasters(db, engine) -> None:
    reply = await forecast_router.get_forecast_models(db=db, _user=None)
    assert (reply.engine_supports, reply.models, reply.max_horizon) == (True, ["tfm:q8", "tfm:f32"], 128)
    assert reply.default_model == "tfm:q8"  # the first installed until an admin picks one


@pytest.mark.asyncio
async def test_an_engine_without_forecasting_lists_nothing(db, engine, monkeypatch) -> None:
    monkeypatch.setattr(forecast_service.registry, "active", lambda: _Engine(supports=False))
    reply = await forecast_router.get_forecast_models(db=db, _user=None)
    assert (reply.engine_supports, reply.models) == (False, [])


async def _events(db, request: ForecastRunRequest) -> list[dict]:
    response = await forecast_router.run_forecast(request, db=db, _user=None)
    return [json.loads(line) async for line in response.body_iterator]


@pytest.mark.asyncio
async def test_run_streams_one_forecast_per_series(db, engine) -> None:
    [event] = await _events(db, _request(series=[[1.0, 2.0], [5.0, 6.0, 7.0]]))
    assert event["type"] == "result"
    assert [f["point"] for f in event["result"]["forecasts"]] == [[3.0, 4.0], [3.0, 4.0]]
    assert engine.calls == [("tfm:q8", [[1.0, 2.0], [5.0, 6.0, 7.0]], 2, None)]  # no time limit by default


@pytest.mark.asyncio
async def test_a_slow_forecast_sends_heartbeats(db, engine, monkeypatch) -> None:
    monkeypatch.setattr(forecast_service, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(forecast_service.registry, "active", lambda: _Engine(delay=0.05))
    events = await _events(db, _request())
    assert {e["type"] for e in events[:-1]} == {"waiting"}
    assert events[-1]["type"] == "result"


@pytest.mark.asyncio
async def test_the_time_limit_stops_a_slow_forecast(db, engine, monkeypatch) -> None:
    monkeypatch.setattr(forecast_service, "HEARTBEAT_SECONDS", 0.01)
    slow = _Engine(delay=30)
    monkeypatch.setattr(forecast_service.registry, "active", lambda: slow)
    await forecast_router.set_forecast_limits(ForecastLimits(time_limit_seconds=1), db=db, _admin=None)

    events = await _events(db, _request())

    assert events[-1] == {
        "type": "error",
        "elapsed_seconds": events[-1]["elapsed_seconds"],
        "detail": "The forecast took longer than the 1 s limit.",
    }
    await asyncio.sleep(0)  # the cancel lands on the next loop turn
    assert slow.calls[0][3] == 1 and slow.cancelled


@pytest.mark.asyncio
@pytest.mark.parametrize(("model", "supports"), [("not-installed", True), ("tfm:q8", False)])
async def test_run_refuses_a_missing_model_or_engine(db, engine, monkeypatch, model, supports) -> None:
    monkeypatch.setattr(forecast_service.registry, "active", lambda: _Engine(supports=supports))
    with pytest.raises(HTTPException) as exc:
        await forecast_router.run_forecast(_request(model=model), db=db, _user=None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_an_engine_failure_is_an_error_line(db, engine, monkeypatch) -> None:
    monkeypatch.setattr(forecast_service.registry, "active", lambda: _Engine(fails=True))
    [event] = await _events(db, _request())
    assert (event["type"], event["detail"]) == ("error", "Matricxon is down")


@pytest.mark.asyncio
async def test_limits_are_saved_for_every_server_and_reach_the_page(db, engine) -> None:
    assert await forecast_router.get_forecast_limits(db=db, _admin=None) == ForecastLimits(
        max_file_mb=1024, time_limit_seconds=0
    )
    await forecast_router.set_forecast_limits(
        ForecastLimits(max_file_mb=5000, time_limit_seconds=600), db=db, _admin=None
    )

    page = await forecast_router.get_forecast_models(db=db, _user=None)
    assert (page.limits.max_file_mb, page.limits.time_limit_seconds, page.max_series_length) == (5000, 600, 16384)


@pytest.mark.parametrize("bad", [{"max_file_mb": 0}, {"time_limit_seconds": -1}])
def test_limits_must_be_sensible(bad) -> None:
    with pytest.raises(ValidationError):
        ForecastLimits(**bad)


@pytest.mark.parametrize(
    "bad",
    [{"series": [[1.0]]}, {"series": []}, {"horizon": 0}, {"horizon": 129}, {"series": [[1.0, float("nan")]]}],
)
def test_bad_requests_are_rejected(bad) -> None:
    with pytest.raises(ValidationError):
        _request(**bad)


def test_a_long_series_keeps_only_its_latest_values() -> None:
    values = [float(i) for i in range(MAX_SERIES_LENGTH + 10)]
    assert _request(series=[values]).series[0] == values[-MAX_SERIES_LENGTH:]


@pytest.mark.asyncio
async def test_admin_catalog_marks_installed_entries(db, engine) -> None:
    catalog = await forecast_router.get_forecast_model_catalog(db=db, _admin=None)
    by_tag = {e.tag: e for e in catalog.entries}
    assert by_tag["hf.co/amaye15/timesfm-gguf:q8"].quantization == "Q8_0"
    assert by_tag["hf.co/amaye15/timesfm-gguf:f32"].quantization == "F32"
    assert not any(e.installed for e in catalog.entries)  # "tfm:q8" isn't a curated tag


def test_curated_forecasters_can_be_pulled() -> None:
    assert [m.architecture for m in CATALOG.forecast_models] == ["timesfm25", "timesfm25"]
    assert CATALOG.find_forecast("hf.co/amaye15/timesfm-gguf:q8").locally_runnable


def test_a_forecaster_is_its_own_pin_kind() -> None:
    pin = PinInstalled.from_tags({"name": "tfm:q8", "capabilities": ["forecast"], "size": 1})
    assert (pin.kind, pin.capabilities) == ("forecast", [])


@pytest.mark.asyncio
async def test_the_default_forecasting_model_is_saved_and_preselected(db, engine) -> None:
    setting = await forecast_router.get_default_forecast_model(db=db, _admin=None)
    assert (setting.model, setting.installed) == ("tfm:q8", ["tfm:q8", "tfm:f32"])

    saved = await forecast_router.set_default_forecast_model(ForecastDefaultUpdate(model="tfm:f32"), db=db, _admin=None)
    assert saved.model == "tfm:f32"
    assert (await forecast_router.get_forecast_models(db=db, _user=None)).default_model == "tfm:f32"


@pytest.mark.asyncio
async def test_a_default_that_is_not_installed_is_refused(db, engine) -> None:
    with pytest.raises(HTTPException) as exc:
        await forecast_router.set_default_forecast_model(ForecastDefaultUpdate(model="nope"), db=db, _admin=None)
    assert exc.value.status_code == 400
