import statistics
from datetime import datetime, timedelta
import logging

import httpx

from app.models import EnvironmentReport

logger = logging.getLogger(__name__)


class OpenMeteoClient:
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

    async def fetch_environment_report(
        self, latitude: float, longitude: float, lookahead_days: int
    ) -> EnvironmentReport:
        weather_params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "sunshine_duration,shortwave_radiation_sum,precipitation_probability_max,precipitation_sum",
            "hourly": "relative_humidity_2m,wind_speed_10m,wind_direction_10m",
            "forecast_days": min(max(lookahead_days, 1), 14),
            "timezone": "auto",
        }

        air_params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "pm2_5,pm10",
            # Air-quality endpoint can reject larger forecast windows for some regions/plans.
            "forecast_days": min(max(lookahead_days, 1), 7),
            "timezone": "auto",
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            weather_resp, air_resp = await self._fetch_both(client, weather_params, air_params, lookahead_days)
            past_rain = await self._fetch_past_rain_7_days(client, latitude, longitude)

        weather = weather_resp.json()
        air = air_resp.json()

        daily = weather.get("daily", {})
        hourly_weather = weather.get("hourly", {})
        hourly_air = air.get("hourly", {})

        sunshine_seconds = daily.get("sunshine_duration", [])[:lookahead_days]
        sun_hours = sum(v for v in sunshine_seconds if v is not None) / 3600.0

        shortwave_sum = daily.get("shortwave_radiation_sum", [])[:lookahead_days]
        avg_shortwave = statistics.mean([v for v in shortwave_sum if v is not None]) if shortwave_sum else 0.0

        rain_prob_7 = daily.get("precipitation_probability_max", [])[:7]
        rain_sum_7 = daily.get("precipitation_sum", [])[:7]
        rain_in_next_7_days = any((v or 0) >= 50 for v in rain_prob_7) or any((v or 0) >= 1.0 for v in rain_sum_7)
        rainy_days_next_7_days = sum(
            1
            for prob, mm in zip(rain_prob_7, rain_sum_7)
            if (prob or 0) >= 50 or (mm or 0) >= 1.0
        )
        total_precipitation_next_7_days_mm = float(sum((v or 0.0) for v in rain_sum_7))

        humidity_vals = self._today_slice(hourly_weather.get("time", []), hourly_weather.get("relative_humidity_2m", []))
        wind_speed_vals = self._today_slice(hourly_weather.get("time", []), hourly_weather.get("wind_speed_10m", []))
        wind_dir_vals = self._today_slice(hourly_weather.get("time", []), hourly_weather.get("wind_direction_10m", []))
        pm25_vals = self._today_slice(hourly_air.get("time", []), hourly_air.get("pm2_5", []))
        pm10_vals = self._today_slice(hourly_air.get("time", []), hourly_air.get("pm10", []))

        return EnvironmentReport(
            latitude=latitude,
            longitude=longitude,
            pm25=self._safe_mean(pm25_vals),
            pm10=self._safe_mean(pm10_vals),
            humidity_pct=self._safe_mean(humidity_vals),
            wind_speed_kmh=self._safe_mean(wind_speed_vals),
            wind_direction_deg=self._safe_mean(wind_dir_vals),
            rain_in_next_7_days=rain_in_next_7_days,
            rainy_days_next_7_days=rainy_days_next_7_days,
            total_precipitation_next_7_days_mm=round(total_precipitation_next_7_days_mm, 2),
            rain_in_prev_7_days=past_rain["rain_in_prev_7_days"],
            rainy_days_prev_7_days=past_rain["rainy_days_prev_7_days"],
            total_precipitation_prev_7_days_mm=round(float(past_rain["total_precipitation_prev_7_days_mm"]), 2),
            sun_hours_next_n_days=round(sun_hours, 2),
            avg_shortwave_radiation_wm2_next_n_days=round(avg_shortwave, 2),
            lookahead_days=lookahead_days,
        )

    async def _fetch_past_rain_7_days(
        self,
        client: httpx.AsyncClient,
        latitude: float,
        longitude: float,
    ) -> dict[str, int | bool | float]:
        end = datetime.utcnow().date() - timedelta(days=1)
        start = end - timedelta(days=6)
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "precipitation_sum",
            "timezone": "auto",
        }
        resp = await client.get(self.ARCHIVE_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
        daily = payload.get("daily", {})
        rain_vals = daily.get("precipitation_sum", []) or []
        rainy_days = sum(1 for v in rain_vals if (v or 0) >= 1.0)
        total_precip = float(sum((v or 0.0) for v in rain_vals))
        return {
            "rain_in_prev_7_days": rainy_days > 0,
            "rainy_days_prev_7_days": rainy_days,
            "total_precipitation_prev_7_days_mm": total_precip,
        }

    async def _fetch_both(
        self,
        client: httpx.AsyncClient,
        weather_params: dict,
        air_params: dict,
        lookahead_days: int,
    ):
        weather_task = client.get(self.FORECAST_URL, params=weather_params)
        air_task = self._fetch_air_with_fallback(client, air_params, lookahead_days)
        weather_resp, air_resp = await weather_task, await air_task
        weather_resp.raise_for_status()
        return weather_resp, air_resp

    async def _fetch_air_with_fallback(
        self,
        client: httpx.AsyncClient,
        air_params: dict,
        lookahead_days: int,
    ) -> httpx.Response:
        attempts = [
            {"forecast_days": min(max(lookahead_days, 1), 7)},
            {"forecast_days": 3},
            {},  # last resort: provider default horizon
        ]

        last_exc: Exception | None = None
        for patch in attempts:
            params = {k: v for k, v in air_params.items() if k != "forecast_days"}
            params.update(patch)
            try:
                resp = await client.get(self.AIR_QUALITY_URL, params=params)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning(
                    "Air-quality request failed (status=%s) with params=%s",
                    exc.response.status_code if exc.response else "unknown",
                    params,
                )
                if exc.response is None or exc.response.status_code != 400:
                    raise

        if last_exc:
            raise last_exc
        raise RuntimeError("Air-quality request failed unexpectedly with no response")

    @staticmethod
    def _safe_mean(values: list[float | None]) -> float | None:
        clean = [v for v in values if v is not None]
        return round(statistics.mean(clean), 2) if clean else None

    @staticmethod
    def _today_slice(times: list[str], values: list[float | None]) -> list[float | None]:
        today = datetime.now().date().isoformat()
        selected: list[float | None] = []
        for ts, value in zip(times, values):
            if ts.startswith(today):
                selected.append(value)
        return selected

if __name__ == "__main__":
    import asyncio
    import json

    async def _demo() -> None:
        client = OpenMeteoClient()

        # Example: San Luis Obispo, CA
        report = await client.fetch_environment_report(
            latitude=35.2828,
            longitude=-120.6596,
            lookahead_days=3,
        )

        print("EnvironmentReport object:")
        print(report)

        print("\nAs JSON:")
        print(json.dumps(report.model_dump(), indent=2))

    asyncio.run(_demo())
