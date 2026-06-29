"""Weather data from Open-Meteo (free API, no key required, stdlib only)."""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

_BASE_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherConfigError(Exception):
    """Raised when weather location is not configured."""


@dataclass
class WeatherConfig:
    latitude: float
    longitude: float
    timeout_seconds: float = 10.0


@dataclass
class WeatherResult:
    success: bool
    current_temp_c: float = 0.0
    current_weathercode: int = 0
    current_windspeed_kmh: float = 0.0
    current_precipitation_mm: float = 0.0
    max_temp_c: float = 0.0
    min_temp_c: float = 0.0
    daily_weathercode: int = 0
    daily_precipitation_mm: float = 0.0
    location_name: str = ""
    error: str = ""


def _wmo_description(code: int) -> str:
    return WMO_CODES.get(code, f"Weather code {code}")


def get_weather(
    config: WeatherConfig | None = None,
    *,
    opener: Callable | None = None,
) -> WeatherResult:
    """Fetch current conditions and today's forecast from Open-Meteo.

    Args:
        config: Weather configuration with lat/lon. Reads from env defaults if None.
        opener: Injectable callable replacing urllib.request.urlopen (for tests).
    """
    if config is None:
        from eclipse_agent.settings import load_settings

        s = load_settings()
        config = WeatherConfig(latitude=s.weather_lat, longitude=s.weather_lon)

    if config.latitude == 0.0 and config.longitude == 0.0:
        return WeatherResult(
            success=False,
            error="Weather location not configured. Set ECLIPSE_WEATHER_LAT and ECLIPSE_WEATHER_LON.",
        )

    params = urllib.parse.urlencode(
        {
            "latitude": config.latitude,
            "longitude": config.longitude,
            "current": "temperature_2m,weathercode,windspeed_10m,precipitation",
            "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
            "forecast_days": 1,
            "timezone": "auto",
        }
    )
    url = f"{_BASE_URL}?{params}"
    _opener = opener or urllib.request.urlopen

    try:
        response = _opener(url, timeout=config.timeout_seconds)
        if hasattr(response, "read"):
            raw = response.read()
        else:
            raw = response
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError):
        return WeatherResult(
            success=False,
            error=f"Weather fetch timed out after {int(config.timeout_seconds)}s",
        )
    except (json.JSONDecodeError, ValueError):
        return WeatherResult(
            success=False,
            error="Unexpected response format from Open-Meteo",
        )

    try:
        # Handle both old and new Open-Meteo response shapes
        if "current_weather" in data:
            cw = data["current_weather"]
            temp = float(cw["temperature"])
            code = int(cw["weathercode"])
            wind = float(cw["windspeed"])
            precip = 0.0
        else:
            cw = data["current"]
            temp = float(cw["temperature_2m"])
            code = int(cw["weathercode"])
            wind = float(cw["windspeed_10m"])
            precip = float(cw.get("precipitation", 0.0))

        daily = data["daily"]
        max_temp = float(daily["temperature_2m_max"][0])
        min_temp = float(daily["temperature_2m_min"][0])
        daily_code = int(daily["weathercode"][0])
        daily_precip = float(daily["precipitation_sum"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return WeatherResult(
            success=False,
            error="Unexpected response format from Open-Meteo",
        )

    return WeatherResult(
        success=True,
        current_temp_c=temp,
        current_weathercode=code,
        current_windspeed_kmh=wind,
        current_precipitation_mm=precip,
        max_temp_c=max_temp,
        min_temp_c=min_temp,
        daily_weathercode=daily_code,
        daily_precipitation_mm=daily_precip,
    )


def render_weather(result: WeatherResult) -> str:
    """Return a natural-language one-sentence weather description."""
    if not result.success:
        return f"Weather unavailable: {result.error}"
    condition = _wmo_description(result.current_weathercode)
    precip_text = (
        f", {result.daily_precipitation_mm:.1f} mm precipitation expected"
        if result.daily_precipitation_mm > 0
        else ", no precipitation expected"
    )
    return (
        f"Currently {result.current_temp_c:.1f}°C and {condition}, "
        f"wind {result.current_windspeed_kmh:.0f} km/h. "
        f"Today's high {result.max_temp_c:.1f}°C, low {result.min_temp_c:.1f}°C{precip_text}."
    )


# --- WeatherClient (class-based API requested by task description) ---

_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes


class WeatherClient:
    """Stateful weather client with response caching."""

    def __init__(self, lat: float, lon: float, *, opener: Callable | None = None) -> None:
        if lat == 0.0 and lon == 0.0:
            raise WeatherConfigError(
                "Weather location not configured. Set ECLIPSE_WEATHER_LAT and ECLIPSE_WEATHER_LON."
            )
        self._config = WeatherConfig(latitude=lat, longitude=lon)
        self._opener = opener
        self._cache: dict | None = None
        self._cache_time: datetime.datetime | None = None

    def _is_cache_valid(self) -> bool:
        if self._cache is None or self._cache_time is None:
            return False
        elapsed = (datetime.datetime.now() - self._cache_time).total_seconds()
        return elapsed < _CACHE_TTL_SECONDS

    def current_conditions(self) -> dict:
        """Return current weather conditions, using cache if fresh."""
        if not self._is_cache_valid():
            self._refresh_cache()
        assert self._cache is not None
        return self._cache["current"]

    def forecast_today(self) -> dict:
        """Return today's forecast."""
        if not self._is_cache_valid():
            self._refresh_cache()
        assert self._cache is not None
        return self._cache["forecast"]

    def _refresh_cache(self) -> None:
        result = get_weather(self._config, opener=self._opener)
        if not result.success:
            raise RuntimeError(result.error)
        self._cache = {
            "current": {
                "temperature": result.current_temp_c,
                "wind_speed": result.current_windspeed_kmh,
                "condition": _wmo_description(result.current_weathercode),
            },
            "forecast": {
                "max_temp": result.max_temp_c,
                "min_temp": result.min_temp_c,
                "precipitation_mm": result.daily_precipitation_mm,
            },
        }
        self._cache_time = datetime.datetime.now()


def describe_weather(lat: float, lon: float) -> str:
    """Return a natural-language one-sentence weather description."""
    config = WeatherConfig(latitude=lat, longitude=lon)
    result = get_weather(config)
    return render_weather(result)
