"""
Address geocoding and straight-line distance calculations.
Uses Nominatim (free, OpenStreetMap) — rate-limited to 1 req/sec.
"""

import math
import time
from typing import Callable, Optional

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

NOMINATIM_DELAY = 1.1  # seconds — ToS requires >= 1 req/sec
EARTH_RADIUS_MILES = 3958.8

_geocoder = Nominatim(user_agent="rentsearch-app-v1")


def geocode_address(address: str, retries: int = 3) -> Optional[tuple[float, float]]:
    """Geocode a single address to (lat, lon).
    Sleeps NOMINATIM_DELAY before each call.
    Returns None on failure.
    """
    for attempt in range(retries):
        try:
            time.sleep(NOMINATIM_DELAY)
            location = _geocoder.geocode(address, timeout=10)
            if location:
                return (location.latitude, location.longitude)
        except GeocoderTimedOut:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
        except GeocoderServiceError:
            break
    return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance between two coordinates in miles."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_MILES * c


def compute_weighted_distance(
    apt_coords: tuple[float, float],
    locations: list[dict],
) -> dict:
    """Compute weighted average distance from an apartment to all user locations.

    Each location dict must have 'coords' (lat, lon) and 'weight' (int 1-10).
    Locations without coords are skipped.

    Returns:
        {
            'weighted_avg_miles': float or None,
            'per_location': {label: miles, ...}
        }
    """
    per_location: dict[str, float] = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for loc in locations:
        coords = loc.get("coords")
        if not coords:
            continue
        miles = haversine_miles(apt_coords[0], apt_coords[1], coords[0], coords[1])
        label = loc.get("label", "Location")
        per_location[label] = round(miles, 2)
        weight = loc.get("weight", 5)
        weighted_sum += miles * weight
        weight_total += weight

    weighted_avg = (weighted_sum / weight_total) if weight_total > 0 else None
    return {
        "weighted_avg_miles": round(weighted_avg, 2) if weighted_avg is not None else None,
        "per_location": per_location,
    }


def distance_to_score(weighted_avg_miles: Optional[float], max_distance_miles: float) -> float:
    """Convert weighted average distance to a 0–10 score.
    Returns 0.0 if weighted_avg_miles is None.
    """
    if weighted_avg_miles is None:
        return 0.0
    return round(10.0 * max(0.0, 1.0 - weighted_avg_miles / max_distance_miles), 2)


def compute_distance_score(
    apt_coords: tuple[float, float],
    locations: list[dict],
) -> float:
    """Weighted average of per-location distance scores using each location's own max_distance.
    Each location contributes score_i = max(0, 1 - dist_i / loc_max_dist) * 10,
    weighted by the location's importance weight.
    Returns 0.0 if no locations have coords.
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for loc in locations:
        coords = loc.get("coords")
        if not coords:
            continue
        miles = haversine_miles(apt_coords[0], apt_coords[1], coords[0], coords[1])
        max_dist = float(loc.get("max_distance") or 15)
        score = max(0.0, 1.0 - miles / max_dist) * 10.0
        weight = loc.get("weight", 5)
        weighted_sum += score * weight
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return round(weighted_sum / weight_total, 2)


def is_too_far(
    apt_coords: tuple[float, float],
    locations: list[dict],
) -> bool:
    """Return True if the apartment exceeds ANY location's individual max_distance."""
    for loc in locations:
        coords = loc.get("coords")
        if not coords:
            continue
        miles = haversine_miles(apt_coords[0], apt_coords[1], coords[0], coords[1])
        max_dist = float(loc.get("max_distance") or 15)
        if miles > max_dist:
            return True
    return False


def geocode_all_locations(
    locations: list[dict],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """Geocode every user-defined location in-place.
    Attaches 'coords' tuple (lat, lon) or None to each location dict.
    Returns the updated list.
    """
    total = len(locations)
    for i, loc in enumerate(locations):
        label = loc.get("label", "Location")
        address = loc.get("address", "")
        if progress_callback:
            progress_callback(i / max(total, 1), f"Geocoding '{label}'...")
        coords = geocode_address(address) if address.strip() else None
        loc["coords"] = coords
        if coords is None and progress_callback:
            progress_callback(
                (i + 1) / max(total, 1),
                f"Could not geocode '{label}' — distance to this location will be skipped",
            )
    return locations
