"""
Per-brand RTSP path table — a fallback for devices that answer RTSP but
don't support (or haven't been given credentials for) ONVIF GetStreamUri.
Pure data + a pure lookup function, deliberately dependency-free so it's
trivially unit tested (see tests/test_rtsp_paths.py) without any network.

Treat this as a best-effort starting point for the user to verify, not
ground truth — path conventions vary by model/firmware even within a brand.
"""

BRAND_PATHS = {
    "hikvision": {"main": "/Streaming/Channels/101", "sub": "/Streaming/Channels/102"},
    "dahua": {"main": "/cam/realmonitor?channel=1&subtype=0", "sub": "/cam/realmonitor?channel=1&subtype=1"},
    "axis": {"main": "/axis-media/media.amp", "sub": "/axis-media/media.amp?resolution=320x240"},
    "uniview": {"main": "/media/video1", "sub": "/media/video2"},
    "reolink": {"main": "/h264Preview_01_main", "sub": "/h264Preview_01_sub"},
    "generic": {"main": "/stream1", "sub": "/stream2"},
}

# Substring aliases seen in real ONVIF GetDeviceInformation Manufacturer
# fields / HTTP server banners, mapped to the canonical BRAND_PATHS key.
_ALIASES = {
    "hikvision": "hikvision", "hik": "hikvision",
    "dahua": "dahua", "imou": "dahua",  # Imou is a Dahua sub-brand, same path convention
    "axis": "axis", "axis communications": "axis",
    "uniview": "uniview", "unv": "uniview",
    "reolink": "reolink",
}


def guess_rtsp_paths(manufacturer: str | None) -> dict:
    """Returns {"main": path, "sub": path} for the best-matching brand, or
    the generic fallback if `manufacturer` is unknown/empty/unrecognized."""
    if not manufacturer:
        return dict(BRAND_PATHS["generic"])
    needle = manufacturer.strip().lower()
    for alias, brand in _ALIASES.items():
        if alias in needle:
            return dict(BRAND_PATHS[brand])
    return dict(BRAND_PATHS["generic"])


def build_rtsp_url(host: str, port: int, username: str, password: str, path: str) -> str:
    """Assembles a full RTSP URL. Kept separate from guess_rtsp_paths so the
    path-guessing logic (the part that's actually brand-specific and worth
    testing) doesn't get tangled up with string formatting."""
    return f"rtsp://{username}:{password}@{host}:{port}{path}"
