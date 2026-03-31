"""
Persistent storage for past search runs.
Saves to ~/.rentsearch/runs/ as JSON files named run_YYYYMMDD_HHMMSS.json.
"""

import json
import datetime
from pathlib import Path
from typing import Optional

RUNS_DIR = Path.home() / ".rentsearch" / "runs"


def _coerce_coords(obj):
    """Recursively convert any [lat, lon] list that looks like coordinates to a tuple."""
    if isinstance(obj, list):
        # A 2-element list of floats is almost certainly a (lat, lon) pair
        if len(obj) == 2 and all(isinstance(v, (int, float)) for v in obj):
            return (float(obj[0]), float(obj[1]))
        return [_coerce_coords(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _coerce_coords(v) for k, v in obj.items()}
    return obj


def save_run(
    city: str,
    min_price: int,
    max_price: int,
    min_beds: int,
    max_beds: int,
    min_baths,
    max_baths,
    locations: list,
    criteria: list,
    listings: list,
    listing_names: Optional[dict] = None,
) -> str:
    """Save a completed search run. Returns the run ID."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now()
    run_id = ts.strftime("run_%Y%m%d_%H%M%S")

    city_part = city.strip() or "Anywhere"
    if min_beds == max_beds:
        beds_part = "Studio" if min_beds == 0 else f"{min_beds}br"
    else:
        beds_part = f"{min_beds}–{max_beds}br"
    price_part = f"${min_price:,}–${max_price:,}/mo"
    label = f"{city_part} · {beds_part} · {price_part}"

    data = {
        "run_id": run_id,
        "label": label,
        "created_at": ts.isoformat(),
        "listing_count": len(listings),
        "params": {
            "city": city,
            "min_price": min_price,
            "max_price": max_price,
            "min_beds": min_beds,
            "max_beds": max_beds,
            "min_baths": min_baths,
            "max_baths": max_baths,
        },
        "locations": locations,
        "criteria": criteria,
        "listings": listings,
        "listing_names": listing_names or {},
    }

    path = RUNS_DIR / f"{run_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    return run_id


def list_runs() -> list[dict]:
    """Return summary metadata for all saved runs, newest first."""
    if not RUNS_DIR.exists():
        return []
    runs = []
    for path in sorted(RUNS_DIR.glob("run_*.json"), reverse=True):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            runs.append({
                "run_id": data.get("run_id", path.stem),
                "label": data.get("label", path.stem),
                "created_at": data.get("created_at", ""),
                "listing_count": data.get("listing_count", 0),
                "params": data.get("params", {}),
            })
        except Exception:  # noqa: BLE001
            pass
    return runs


def load_run(run_id: str) -> Optional[dict]:
    """Load a full run by ID. Returns None if not found or unreadable."""
    path = RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        # JSON serialises tuples as lists; restore coordinate tuples
        raw = _coerce_coords(raw)
        return raw
    except Exception:  # noqa: BLE001
        return None


def delete_run(run_id: str) -> bool:
    """Delete a saved run. Returns True on success."""
    path = RUNS_DIR / f"{run_id}.json"
    try:
        path.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False
