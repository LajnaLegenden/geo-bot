"""Named map configs. Add/edit maps here, trigger them by name from the workflow.

Each entry is the kwargs for GeoGuessr.create_challenge, plus an optional non-API
`weight` (default 1.0) used to scale that map's scores in the combined
leaderboard — so an easier map doesn't dominate the raw-score sum.
"""
from __future__ import annotations

MAPS = {
    "normal": {  # the long-standing daily map
        "map_id": "6029991c5048850001d572a9",
        "time_limit": 120,
        "forbid_moving": True,
    },
    "fast": {  # different, easier map + 15s clock; scores scaled up to compare
        "map_id": "67101e71077612dd6ac8de79",
        "time_limit": 15,
        "forbid_moving": True,
        "weight": 1.75,
    },
}


def create_kwargs(name: str) -> dict:
    """The map's config minus non-API extras (safe to spread into create_challenge)."""
    return {k: v for k, v in MAPS[name].items() if k != "weight"}


def weight(name: str | None) -> float:
    """Per-map score multiplier; 1.0 for unknown/unset (keeps old data unweighted)."""
    return MAPS.get(name, {}).get("weight", 1.0)


if __name__ == "__main__":  # python -m geobot.maps — validate configs
    import inspect

    from .geoguessr import GeoGuessr

    allowed = set(inspect.signature(GeoGuessr.create_challenge).parameters) - {"self"}
    for name in MAPS:
        bad = create_kwargs(name).keys() - allowed
        assert not bad, f"{name}: bad keys {bad}"
        assert MAPS[name].get("map_id"), f"{name}: missing map_id"
    print("maps ok:", ", ".join(MAPS))
