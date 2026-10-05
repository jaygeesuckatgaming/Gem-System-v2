"""
Open-Meteo Weather Client
Fetches current weather + forecast from the free Open-Meteo API (no API key).
"""

import httpx
from typing import Optional, Dict


class WeatherClient:
    def __init__(self, latitude: float = 12.9276, longitude: float = 100.8826):
        """Default coordinates: Pattaya, Thailand."""
        self.latitude = latitude
        self.longitude = longitude
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self.enabled = False

    async def check_connection(self) -> bool:
        """Test the Open-Meteo API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    self.base_url,
                    params={"latitude": self.latitude, "longitude": self.longitude, "current": "temperature_2m"}
                )
                self.enabled = r.status_code == 200
                return self.enabled
        except Exception:
            self.enabled = False
            return False

    async def geocode(self, city_name: str) -> Optional[Dict]:
        """Resolve a city name to latitude/longitude via Open-Meteo geocoding."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city_name, "count": 1, "language": "en", "format": "json"},
                )
                r.raise_for_status()
                results = r.json().get("results", [])
                if not results:
                    return None
                top = results[0]
                return {
                    "name": top.get("name"),
                    "country": top.get("country"),
                    "latitude": top.get("latitude"),
                    "longitude": top.get("longitude"),
                }
        except Exception as e:
            print(f"Geocoding failed: {e}")
            return None

    async def get_current_weather(self, latitude: Optional[float] = None,
                                  longitude: Optional[float] = None) -> Optional[Dict]:
        """Fetch the current weather conditions (for given coords, else default)."""
        lat = latitude if latitude is not None else self.latitude
        lon = longitude if longitude is not None else self.longitude
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    self.base_url,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                                   "weather_code,wind_speed_10m",
                    }
                )
                r.raise_for_status()
                data = r.json()
                current = data.get("current", {})
                return {
                    "time": current.get("time"),
                    "temperature_c": current.get("temperature_2m"),
                    "apparent_c": current.get("apparent_temperature"),
                    "humidity_pct": current.get("relative_humidity_2m"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "weather_code": current.get("weather_code"),
                }
        except Exception as e:
            print(f"Weather fetch failed: {e}")
            return None

    async def get_weather_for_location(self, location_name: str) -> Optional[Dict]:
        """Resolve a location name and return {location, weather} for it."""
        geo = await self.geocode(location_name)
        if not geo:
            return None
        weather = await self.get_current_weather(geo["latitude"], geo["longitude"])
        if not weather:
            return None
        return {"location": f"{geo['name']}, {geo.get('country', '')}", "weather": weather}

    @staticmethod
    def describe_weather(data: Dict) -> str:
        """Turn raw weather data into a short human-readable sentence."""
        try:
            temp = data.get("temperature_c")
            feels = data.get("apparent_c")
            humidity = data.get("humidity_pct")
            wind = data.get("wind_speed_kmh")
            code = data.get("weather_code")

            code_map = {
                0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
                45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
                61: "light rain", 63: "rain", 65: "heavy rain", 80: "light showers",
                81: "showers", 82: "heavy showers", 95: "thunderstorms",
            }
            condition = code_map.get(code, "unknown conditions")

            parts = [f"{temp}°C", condition]
            if humidity is not None:
                parts.append(f"{humidity}% humidity")
            if wind is not None:
                parts.append(f"{wind} km/h wind")
            if feels is not None and feels != temp:
                parts.append(f"feels like {feels}°C")
            return ", ".join(parts)
        except Exception:
            return "Unknown conditions"
