"""Geospatial utility functions."""

from math import atan2, cos, radians, sin, sqrt


def distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Return the great-circle distance in metres between two WGS-84 coordinates."""
    R = 6_371_000
    dlat = radians(lat_b - lat_a)
    dlon = radians(lon_b - lon_a)
    a = sin(dlat / 2) ** 2 + cos(radians(lat_a)) * cos(radians(lat_b)) * sin(dlon / 2) ** 2
    a = min(1, max(0, a))
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))
