"""Hermetic tests for weather.py — no real network calls."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from eclipse_agent.weather import (
    WeatherClient,
    WeatherConfig,
    WeatherConfigError,
    WeatherResult,
    _wmo_description,
    get_weather,
    render_weather,
)

# --- Fixtures ---

_CURRENT_WEATHER_JSON = {
    "current_weather": {
        "temperature": 18.5,
        "weathercode": 2,
        "windspeed": 15.0,
    },
    "daily": {
        "temperature_2m_max": [24.0],
        "temperature_2m_min": [12.0],
        "weathercode": [3],
        "precipitation_sum": [1.5],
    },
}


def _make_opener(payload: dict):
    """Return a fake opener that yields payload as JSON bytes."""

    def _opener(url, timeout=10):
        data = json.dumps(payload).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        return mock_resp

    return _opener


# --- Tests ---


def test_weather_unconfigured_raises() -> None:
    """lat=0.0, lon=0.0 should raise WeatherConfigError on WeatherClient."""
    with pytest.raises(WeatherConfigError):
        WeatherClient(lat=0.0, lon=0.0)


def test_weather_unconfigured_returns_error_result() -> None:
    """get_weather with 0.0/0.0 config returns a failure result (not exception)."""
    config = WeatherConfig(latitude=0.0, longitude=0.0)
    result = get_weather(config)
    assert not result.success
    assert "not configured" in result.error.lower()


def test_current_conditions_parses_response() -> None:
    """Inject a fake opener; assert temperature, wind_speed, condition are parsed."""
    opener = _make_opener(_CURRENT_WEATHER_JSON)
    client = WeatherClient(lat=40.0, lon=-3.0, opener=opener)

    conditions = client.current_conditions()

    assert conditions["temperature"] == pytest.approx(18.5)
    assert conditions["wind_speed"] == pytest.approx(15.0)
    assert isinstance(conditions["condition"], str)
    assert len(conditions["condition"]) > 0


def test_cache_prevents_second_call() -> None:
    """Call current_conditions() twice; opener must be called only once."""
    call_count = [0]

    def counting_opener(url, timeout=10):
        call_count[0] += 1
        data = json.dumps(_CURRENT_WEATHER_JSON).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        return mock_resp

    client = WeatherClient(lat=40.0, lon=-3.0, opener=counting_opener)
    client.current_conditions()
    client.current_conditions()

    assert call_count[0] == 1


def test_wmo_code_fallback() -> None:
    """Unknown WMO code returns a non-empty string (no crash)."""
    result = _wmo_description(999)
    assert isinstance(result, str)
    assert len(result) > 0


def test_forecast_today_parses_response() -> None:
    """Inject fake opener; assert max_temp, min_temp, precipitation_mm."""
    opener = _make_opener(_CURRENT_WEATHER_JSON)
    client = WeatherClient(lat=40.0, lon=-3.0, opener=opener)

    forecast = client.forecast_today()

    assert forecast["max_temp"] == pytest.approx(24.0)
    assert forecast["min_temp"] == pytest.approx(12.0)
    assert forecast["precipitation_mm"] == pytest.approx(1.5)


def test_get_weather_timeout_returns_error() -> None:
    """When opener raises URLError, get_weather returns a failure result."""
    import urllib.error

    def timeout_opener(url, timeout=10):
        raise urllib.error.URLError("timed out")

    config = WeatherConfig(latitude=40.0, longitude=-3.0)
    result = get_weather(config, opener=timeout_opener)

    assert not result.success
    assert "timed out" in result.error.lower() or "weather fetch" in result.error.lower()


def test_get_weather_bad_json_returns_error() -> None:
    """When opener returns garbage JSON, get_weather returns a failure result."""

    def bad_opener(url, timeout=10):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        return mock_resp

    config = WeatherConfig(latitude=40.0, longitude=-3.0)
    result = get_weather(config, opener=bad_opener)

    assert not result.success
    assert "format" in result.error.lower() or "unexpected" in result.error.lower()


def test_render_weather_success() -> None:
    """render_weather returns a readable sentence for a successful result."""
    result = WeatherResult(
        success=True,
        current_temp_c=20.0,
        current_weathercode=0,
        current_windspeed_kmh=10.0,
        current_precipitation_mm=0.0,
        max_temp_c=25.0,
        min_temp_c=15.0,
        daily_weathercode=0,
        daily_precipitation_mm=0.0,
    )
    text = render_weather(result)
    assert "20.0" in text
    assert "Clear" in text or "°C" in text


def test_render_weather_failure() -> None:
    """render_weather on a failed result returns an error string."""
    result = WeatherResult(success=False, error="some error")
    text = render_weather(result)
    assert "unavailable" in text.lower() or "some error" in text
