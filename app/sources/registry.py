from app.sources.greenhouse import GreenhouseSource
from app.sources.lever import LeverSource

ALL_SOURCES = {
    "greenhouse": GreenhouseSource(),
    "lever": LeverSource(),
}


def enabled_sources(prefs: dict) -> list:
    out = []
    cfg = prefs.get("sources") or {}
    for name, client in ALL_SOURCES.items():
        if (cfg.get(name) or {}).get("enabled"):
            out.append(client)
    return out
