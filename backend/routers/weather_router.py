# ============================================================
# GREEN App — Weather Router
#
# Proxies OpenWeatherMap API calls so the API key stays
# server-side and is never exposed to the browser.
#
# Endpoints:
#   GET /api/weather/current   — current conditions
#   GET /api/weather/forecast  — 5-day / 3-hour forecast
#   GET /api/weather/agro-tip  — agronomic advice from conditions
# ============================================================

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from config import WEATHER_API_KEY, OPENWEATHER_BASE_URL
from models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/weather", tags=["Weather"])

# Cameroon region → coordinates mapping (fallback when no GPS)
CAMEROON_COORDS = {
    "yaounde":   {"lat": 3.8480,  "lon": 11.5021, "label": "Yaoundé, Centre"},
    "douala":    {"lat": 4.0511,  "lon": 9.7679,  "label": "Douala, Littoral"},
    "bafoussam": {"lat": 5.4737,  "lon": 10.4175, "label": "Bafoussam, Ouest"},
    "garoua":    {"lat": 9.3017,  "lon": 13.3921, "label": "Garoua, Nord"},
    "maroua":    {"lat": 10.5910, "lon": 14.3158, "label": "Maroua, Extrême-Nord"},
    "bertoua":   {"lat": 4.5833,  "lon": 13.6833, "label": "Bertoua, Est"},
    "buea":      {"lat": 4.1597,  "lon": 9.2416,  "label": "Buea, Sud-Ouest"},
    "ebolowa":   {"lat": 2.9000,  "lon": 11.1500, "label": "Ebolowa, Sud"},
    "ngaoundere":{"lat": 7.3265,  "lon": 13.5840, "label": "Ngaoundéré, Adamaoua"},
    "bamenda":   {"lat": 5.9527,  "lon": 10.1460, "label": "Bamenda, Nord-Ouest"},
}

DEFAULT_CITY = "yaounde"


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _require_key():
    if not WEATHER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Service météo non configuré. Définissez WEATHER_API_KEY dans .env"
        )


def _resolve_coords(city: Optional[str], lat: Optional[float], lon: Optional[float]) -> dict:
    """Return OWM query params and a display label."""
    if lat is not None and lon is not None:
        return {"params": {"lat": lat, "lon": lon}, "label": f"{lat:.4f}°N, {lon:.4f}°E"}

    key = (city or DEFAULT_CITY).lower().strip()
    preset = CAMEROON_COORDS.get(key)
    if preset:
        return {"params": {"lat": preset["lat"], "lon": preset["lon"]}, "label": preset["label"]}

    # Pass city name directly to OWM (handles any city worldwide)
    return {"params": {"q": f"{city},CM"}, "label": city}


def _agro_tip(temp: float, humidity: float, weather_id: int) -> dict:
    """
    Return an agronomic risk level and advice based on current conditions.
    weather_id = OWM condition code (2xx thunder, 3xx drizzle, 5xx rain, 8xx clear/cloud…)
    """
    # Rain / thunder → fungal disease risk
    if 200 <= weather_id < 600:
        return {
            "level":   "warning",
            "message": (
                "Conditions humides — risque élevé de propagation fongique (mildiou, "
                "alternariose). Inspectez les cultures et envisagez un traitement préventif."
            ),
        }
    if humidity > 85:
        return {
            "level":   "warning",
            "message": (
                f"Humidité élevée ({humidity} %) — conditions favorables aux champignons "
                "et bactéries. Vérifiez le manioc et la tomate."
            ),
        }
    if temp > 36:
        return {
            "level":   "caution",
            "message": (
                f"Chaleur intense ({temp:.0f} °C) — stress hydrique possible sur les cultures "
                "sensibles. Assurez une irrigation adéquate."
            ),
        }
    if temp < 14:
        return {
            "level":   "info",
            "message": (
                f"Températures fraîches ({temp:.0f} °C) — croissance ralentie. "
                "Idéal pour les cultures de saison fraîche ; surveillez les risques de gel en altitude."
            ),
        }
    return {
        "level":   "ok",
        "message": "Conditions agronomiques favorables — aucune alerte météo immédiate.",
    }


def _format_current(raw: dict, label: str) -> dict:
    """Flatten OWM /weather response into a clean dict."""
    main    = raw.get("main", {})
    wind    = raw.get("wind", {})
    weather = raw.get("weather", [{}])[0]
    sys     = raw.get("sys", {})

    temp     = main.get("temp",       0.0)
    humidity = main.get("humidity",   0)
    w_id     = weather.get("id",      800)

    tip = _agro_tip(temp, humidity, w_id)

    return {
        "city":        raw.get("name", label),
        "label":       label,
        "country":     sys.get("country", "CM"),
        "temp":        round(temp, 1),
        "feels_like":  round(main.get("feels_like", temp), 1),
        "temp_min":    round(main.get("temp_min", temp), 1),
        "temp_max":    round(main.get("temp_max", temp), 1),
        "humidity":    humidity,
        "pressure":    main.get("pressure", 0),
        "wind_speed":  round(wind.get("speed", 0) * 3.6, 1),   # m/s → km/h
        "wind_deg":    wind.get("deg", 0),
        "clouds":      raw.get("clouds", {}).get("all", 0),
        "weather_id":  w_id,
        "description": weather.get("description", "").capitalize(),
        "icon":        weather.get("icon", "01d"),
        "sunrise":     sys.get("sunrise"),
        "sunset":      sys.get("sunset"),
        "agro_tip":    tip,
    }


def _format_forecast(raw: dict, label: str) -> list:
    """
    Convert OWM /forecast (3h steps) to a list of daily summaries.
    Groups by date, picks the midday (12:00) entry or the first of the day.
    """
    from collections import defaultdict
    import datetime

    days: dict = defaultdict(list)
    for item in raw.get("list", []):
        date_str = item["dt_txt"][:10]
        days[date_str].append(item)

    result = []
    for date_str in sorted(days.keys())[:5]:
        entries = days[date_str]
        # Pick midday entry if available, else first
        midday = next(
            (e for e in entries if "12:00:00" in e["dt_txt"]),
            entries[len(entries) // 2],
        )
        main    = midday.get("main", {})
        weather = midday.get("weather", [{}])[0]
        wind    = midday.get("wind", {})
        temp    = main.get("temp", 0)
        humidity = main.get("humidity", 0)
        w_id    = weather.get("id", 800)

        result.append({
            "date":        date_str,
            "day":         datetime.date.fromisoformat(date_str).strftime("%A"),   # Monday…
            "temp_max":    round(max(e["main"]["temp"] for e in entries), 1),
            "temp_min":    round(min(e["main"]["temp"] for e in entries), 1),
            "temp":        round(temp, 1),
            "humidity":    humidity,
            "wind_speed":  round(wind.get("speed", 0) * 3.6, 1),
            "weather_id":  w_id,
            "description": weather.get("description", "").capitalize(),
            "icon":        weather.get("icon", "01d"),
            "agro_tip":    _agro_tip(temp, humidity, w_id),
        })
    return result


# ─────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────

@router.get("/current", summary="Météo actuelle pour une ville ou des coordonnées GPS")
async def get_current_weather(
    city: Optional[str]  = Query(None, description="Ville (ex: Yaoundé, Douala…)"),
    lat:  Optional[float]= Query(None, description="Latitude GPS"),
    lon:  Optional[float]= Query(None, description="Longitude GPS"),
    current_user: User   = Depends(get_current_user),
):
    """
    Retourne les conditions météo actuelles via OpenWeatherMap.
    Priorité : coordonnées GPS > nom de ville > Yaoundé par défaut.
    """
    _require_key()
    resolved = _resolve_coords(city, lat, lon)

    params = {
        **resolved["params"],
        "appid": WEATHER_API_KEY,
        "units": "metric",
        "lang":  "fr",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{OPENWEATHER_BASE_URL}/weather", params=params)
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Ville introuvable : {city}")
            r.raise_for_status()
            return _format_current(r.json(), resolved["label"])
    except httpx.HTTPError as exc:
        logger.error(f"[Weather] OpenWeather error: {exc}")
        raise HTTPException(status_code=502, detail="Service météo indisponible.")


@router.get("/forecast", summary="Prévisions sur 5 jours (résumé journalier)")
async def get_forecast(
    city: Optional[str]  = Query(None),
    lat:  Optional[float]= Query(None),
    lon:  Optional[float]= Query(None),
    current_user: User   = Depends(get_current_user),
):
    """Retourne les prévisions météo sur 5 jours via OpenWeatherMap."""
    _require_key()
    resolved = _resolve_coords(city, lat, lon)

    params = {
        **resolved["params"],
        "appid": WEATHER_API_KEY,
        "units": "metric",
        "lang":  "fr",
        "cnt":   40,   # 5 days × 8 slots/day
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{OPENWEATHER_BASE_URL}/forecast", params=params)
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Ville introuvable : {city}")
            r.raise_for_status()
            return {
                "city":     resolved["label"],
                "forecast": _format_forecast(r.json(), resolved["label"]),
            }
    except httpx.HTTPError as exc:
        logger.error(f"[Weather] OpenWeather forecast error: {exc}")
        raise HTTPException(status_code=502, detail="Service météo indisponible.")
