"""
ONVIF WS-Discovery — the primary discovery method, per the decision that
this scanner runs on the same VLAN/L2 segment as the cameras (multicast
reach is viable here). Finds compliant cameras with NO credentials needed,
via a multicast probe to 239.255.255.250:3702.

Constraint worth restating loudly in the UI, not just here: this only
works on the same L2 segment/VLAN as the scanner — cameras behind a router
or on a separate camera VLAN will never appear via this path. That's not a
bug, it's what multicast discovery fundamentally is; subnet_sweep.py is
the fallback for exactly that case.

GetDeviceInformation / GetStreamUri (onvif-zeep, sync — called via
asyncio.to_thread from the async scan job, fine given scan concurrency is
already capped) only run AFTER the user supplies credentials for a
discovered device; WS-Discovery itself needs none.
"""

import re
from typing import Optional
from urllib.parse import urlparse

from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery


def _extract_ip(xaddr: str) -> Optional[str]:
    m = re.search(r"://([^:/]+)", xaddr)
    return m.group(1) if m else None


def discover_devices(timeout: float = 5.0) -> list:
    """Blocking (wsdiscovery is sync) — call via asyncio.to_thread."""
    wsd = WSDiscovery()
    wsd.start()
    try:
        services = wsd.searchServices(timeout=timeout)
    finally:
        wsd.stop()

    devices = []
    for service in services:
        xaddrs = service.getXAddrs()
        if not xaddrs:
            continue
        devices.append({
            "onvif_xaddr": xaddrs[0],
            "ip": _extract_ip(xaddrs[0]),
            "types": [str(t) for t in (service.getTypes() or [])],
        })
    return devices


def get_device_info(xaddr: str, username: str, password: str) -> dict:
    """Best-effort — any field may be missing if the device doesn't
    support that ONVIF service/profile. Never raises; failures land in
    *_error keys so the caller can show them instead of crashing the scan."""
    from onvif import ONVIFCamera

    parsed = urlparse(xaddr)
    host, port = parsed.hostname, (parsed.port or 80)
    info: dict = {}

    try:
        cam = ONVIFCamera(host, port, username, password)
        device_info = cam.devicemgmt.GetDeviceInformation()
        info["manufacturer"] = getattr(device_info, "Manufacturer", None)
        info["model"] = getattr(device_info, "Model", None)
        info["firmware"] = getattr(device_info, "FirmwareVersion", None)
        info["serial"] = getattr(device_info, "SerialNumber", None)
    except Exception as e:
        info["device_info_error"] = str(e)
        return info

    try:
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        if profiles:
            req = media.create_type("GetStreamUri")
            req.ProfileToken = profiles[0].token
            req.StreamSetup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
            info["main_stream_uri"] = getattr(media.GetStreamUri(req), "Uri", None)
            if len(profiles) > 1:
                req2 = media.create_type("GetStreamUri")
                req2.ProfileToken = profiles[-1].token
                req2.StreamSetup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
                info["sub_stream_uri"] = getattr(media.GetStreamUri(req2), "Uri", None)
    except Exception as e:
        info["stream_uri_error"] = str(e)

    return info
