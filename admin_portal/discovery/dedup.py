"""
Re-scan dedup: a camera that changed IP via DHCP is the same camera, not a
new one. Matches in priority order MAC -> serial -> IP (the spec's exact
ordering) since MAC/serial survive a DHCP lease change and IP doesn't.

Pure, dependency-free, no I/O — trivially unit tested (see
tests/test_discovery_dedup.py) with fabricated "existing camera" fixtures,
no real network or database involved.
"""

from typing import Optional, TypedDict


class ExistingCamera(TypedDict, total=False):
    camera_id: str
    mac: Optional[str]
    serial: Optional[str]
    ip: Optional[str]


def match_existing_camera(
    discovered_mac: Optional[str],
    discovered_serial: Optional[str],
    discovered_ip: Optional[str],
    existing_cameras: list,
):
    """Returns (matched_camera_id, match_reason, ip_changed).
    match_reason is one of "mac" | "serial" | "ip" | None (no match — this
    is a genuinely new device). ip_changed is True only for a mac/serial
    match whose stored IP differs from what was just discovered — the
    signal that flags "same camera, moved" rather than creating a
    duplicate camera row."""
    if discovered_mac:
        norm = discovered_mac.strip().lower()
        for cam in existing_cameras:
            cam_mac = (cam.get("mac") or "").strip().lower()
            if cam_mac and cam_mac == norm:
                ip_changed = bool(cam.get("ip") and discovered_ip and cam["ip"] != discovered_ip)
                return cam["camera_id"], "mac", ip_changed

    if discovered_serial:
        for cam in existing_cameras:
            if cam.get("serial") and cam["serial"] == discovered_serial:
                ip_changed = bool(cam.get("ip") and discovered_ip and cam["ip"] != discovered_ip)
                return cam["camera_id"], "serial", ip_changed

    if discovered_ip:
        for cam in existing_cameras:
            if cam.get("ip") == discovered_ip:
                # IP-only match can't distinguish "same camera" from "a
                # different camera now got this IP via DHCP" — it's a
                # plausible match, not a confirmed one, so never flags
                # ip_changed (there's nothing to flag against).
                return cam["camera_id"], "ip", False

    return None, None, False
