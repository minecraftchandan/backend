"""Cached, rate-limited reverse geocoding via OpenStreetMap Nominatim."""

import hashlib
import json
import time
from threading import Lock
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.database import get_connection

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "SatarkDrishti/1.0 (open-source inspection portal)"
_REQUEST_INTERVAL_SECONDS = 1.0
_request_lock = Lock()
_last_request_at = 0.0


def reverse_geocode(latitude: float, longitude: float) -> dict[str, str]:
    rounded_latitude = round(latitude, 5)
    rounded_longitude = round(longitude, 5)
    cache_key = hashlib.sha256(
        f"{rounded_latitude:.5f},{rounded_longitude:.5f}".encode("ascii")
    ).hexdigest()

    with get_connection() as connection:
        cached = connection.execute(
            "SELECT payload FROM reverse_geocode_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if cached:
        return json.loads(cached["payload"])

    payload = _fetch_nominatim(rounded_latitude, rounded_longitude)
    with get_connection() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO reverse_geocode_cache (cache_key, payload)
            VALUES (?, ?)""",
            (cache_key, json.dumps(payload)),
        )
        cached = connection.execute(
            "SELECT payload FROM reverse_geocode_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    return json.loads(cached["payload"])


def _fetch_nominatim(latitude: float, longitude: float) -> dict[str, str]:
    global _last_request_at
    query = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.5f}",
            "lon": f"{longitude:.5f}",
            "zoom": "18",
            "addressdetails": "1",
        }
    )
    request = Request(
        f"{_NOMINATIM_URL}?{query}",
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
    )
    with _request_lock:
        delay = _REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        _last_request_at = time.monotonic()
        try:
            with urlopen(request, timeout=8) as response:
                result = json.loads(response.read())
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise RuntimeError("OpenStreetMap address lookup is temporarily unavailable.") from error

    if not isinstance(result, dict):
        raise RuntimeError("OpenStreetMap returned an invalid address response.")
    address = result.get("address")
    if not isinstance(address, dict):
        raise RuntimeError("OpenStreetMap could not find an address for these coordinates.")

    fields = (
        "house_number",
        "building",
        "road",
        "pedestrian",
        "footway",
        "residential",
        "neighbourhood",
        "quarter",
        "suburb",
        "city_district",
        "city",
        "town",
        "village",
        "state_district",
        "county",
        "state",
        "postcode",
        "country",
    )
    normalized = {
        key: value.strip()
        for key in fields
        if isinstance((value := address.get(key)), str) and value.strip()
    }
    normalized["display_name"] = str(result.get("display_name") or "").strip()
    if not any(
        normalized.get(key)
        for key in (
            "road", "pedestrian", "footway", "residential", "building",
            "house_number", "neighbourhood", "quarter", "suburb", "village",
            "town", "city",
        )
    ):
        raise RuntimeError("OpenStreetMap returned no nearby street or place name.")
    return normalized
