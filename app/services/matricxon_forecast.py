"""Forecasting through Matricxon's POST /api/forecast (the Forecast page). Fails over like reranking."""

import httpx

from app.services import matricxon_http, matricxon_pool
from app.services.matricxon_errors import MatricxonError, MatricxonHostError, MatricxonReply


class MatricxonForecastClient:
    def __init__(self, timeout_seconds: float | None = None) -> None:
        # None: wait as long as the node works (Admin settings > Forecasting models > Limits).
        self._timeout = httpx.Timeout(timeout_seconds, connect=5.0)

    async def forecast(self, model: str, series: list[list[float]], horizon: int) -> list[dict]:
        """One {"point", "mean", "quantiles"} per series, in order."""
        body = {"model": model, "series": series, "horizon": horizon}

        async def _forecasts_from(host: str) -> list[dict]:
            async with matricxon_http.client(timeout=self._timeout) as client:
                resp = await client.post(f"{host}/api/forecast", json=body)
            if resp.is_error:
                raise MatricxonReply.error(resp.content, resp.status_code)
            return resp.json()["forecasts"]

        try:
            return await matricxon_pool.call_with_failover(_forecasts_from, retry_on=(MatricxonHostError,))
        except (MatricxonError, httpx.HTTPError) as exc:
            raise MatricxonError(f"Forecast request failed: {exc}") from exc
