from __future__ import annotations

from typing import Optional

import httpx

from bot_config import get_settings


async def get_weather_summary(city: str) -> Optional[str]:
    """Простая сводка погоды через OpenWeatherMap (metric, ru).

    Возвращает уже готовый текст или None, если API не настроено/ошибка.
    """
    settings = get_settings()
    api_key = settings.openweather_api_key
    if not api_key:
        return None

    params = {
        "q": city,
        "appid": api_key,
        "units": "metric",
        "lang": "ru",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get("https://api.openweathermap.org/data/2.5/weather", params=params)
        resp.raise_for_status()
        data = resp.json()
        main = data.get("main", {})
        weather_arr = data.get("weather", [])
        temp = main.get("temp")
        feels = main.get("feels_like")
        desc = weather_arr[0].get("description") if weather_arr else ""

        if temp is None:
            return None

        return f"Сейчас в городе {city}: {temp:.0f}°C, ощущается как {feels:.0f}°C. На улице {desc}."
    except Exception:
        return None

