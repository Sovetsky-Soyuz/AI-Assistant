from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


WEATHER_CODES = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Severe thunderstorm with hail",
}


class WeatherError(RuntimeError):
    pass


@dataclass
class WeatherService:
    default_location: str

    def fetch_weather(self, location: str | None = None) -> dict[str, Any]:
        target = (location or self.default_location).strip()
        if not target:
            raise WeatherError("Please provide a location before asking for the weather.")

        place = self._geocode(target)
        forecast = self._forecast(place["latitude"], place["longitude"])
        current = forecast["current"]
        daily = forecast["daily"]

        return {
            "location": f'{place["name"]}, {place["country"]}',
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "condition": WEATHER_CODES.get(current.get("weather_code", -1), "Unknown conditions"),
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_kph": current.get("wind_speed_10m"),
            "precipitation_mm": current.get("precipitation"),
            "high_c": self._pick_first(daily.get("temperature_2m_max", [])),
            "low_c": self._pick_first(daily.get("temperature_2m_min", [])),
            "rain_chance_pct": self._pick_first(daily.get("precipitation_probability_max", [])),
            "advice": self._weather_advice(current, daily),
        }

    def _geocode(self, location: str) -> dict[str, Any]:
        params = urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
        url = f"https://geocoding-api.open-meteo.com/v1/search?{params}"
        payload = self._request_json(url)
        results = payload.get("results") or []
        if not results:
            raise WeatherError(f"I could not find '{location}'. Try a city or country name.")
        return results[0]

    def _forecast(self, latitude: float, longitude: float) -> dict[str, Any]:
        params = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "apparent_temperature",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
                "daily": ",".join(
                    [
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_probability_max",
                    ]
                ),
                "timezone": "auto",
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{params}"
        return self._request_json(url)

    def _request_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "User-Agent": "Orbit-Assistant/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise WeatherError(f"Weather service unavailable right now: {exc}") from exc

    def _pick_first(self, values: list[Any]) -> Any:
        return values[0] if values else None

    def _weather_advice(self, current: dict[str, Any], daily: dict[str, Any]) -> str:
        temp = current.get("temperature_2m")
        rain = self._pick_first(daily.get("precipitation_probability_max", []))
        if isinstance(rain, (int, float)) and rain >= 60:
            return "Carry an umbrella and expect a wet day."
        if isinstance(temp, (int, float)) and temp >= 32:
            return "It is hot outside. Water and shade will help."
        if isinstance(temp, (int, float)) and temp <= 12:
            return "Bring a layer before heading out."
        return "Conditions look manageable for most daily errands."
