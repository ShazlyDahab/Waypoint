"""
Subnet sweep — the fallback discovery strategy for cameras behind a router
or on a separate VLAN from ONVIF WS-Discovery's multicast reach, or that
don't speak ONVIF at all. For a user-supplied CIDR: probes common camera
ports, identifies likely cameras from HTTP banners/headers and RTSP
OPTIONS responses.

Safety: concurrency-capped (asyncio.Semaphore), a bounded per-probe
timeout, and a hard refusal above /22 (1024 hosts) unless the caller
explicitly passes force=True — a sweep of a /24 must not saturate the
network or trip an IDS. Only ever scans the CIDR the caller passes in;
never invents or expands a range on its own.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Optional

import httpx

CAMERA_PORTS = [554, 80, 8000, 8899, 2020]
MAX_HOSTS_WITHOUT_FORCE = 1024  # a /22
DEFAULT_CONCURRENCY = 10
DEFAULT_PROBE_TIMEOUT = 1.5


class RangeTooLarge(ValueError):
    pass


@dataclass
class SweepResult:
    ip: str
    open_ports: list = field(default_factory=list)
    http_banner: Optional[str] = None
    rtsp_responded: bool = False
    guessed_manufacturer: Optional[str] = None


def parse_cidr(cidr: str, force: bool = False) -> list:
    network = ipaddress.ip_network(cidr, strict=False)
    # Check the address count before materializing the host list — for a
    # /8 that's ~16.7M objects, which would make even a *rejected* request
    # burn seconds and memory for nothing.
    num_hosts = max(network.num_addresses - 2, 1)
    if num_hosts > MAX_HOSTS_WITHOUT_FORCE and not force:
        raise RangeTooLarge(
            f"{cidr} has {num_hosts} hosts — refusing to scan more than {MAX_HOSTS_WITHOUT_FORCE} "
            "(a /22) without force=true. Pass a smaller range, or force=true if you really mean it."
        )
    hosts = list(network.hosts()) or [network.network_address]
    return [str(h) for h in hosts]


async def _probe_port(ip: str, port: int, timeout: float) -> bool:
    try:
        fut = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (asyncio.TimeoutError, OSError):
        return False


async def _probe_rtsp_options(ip: str, port: int, timeout: float) -> bool:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.write(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(200), timeout=timeout)
        writer.close()
        return b"RTSP/1.0" in data
    except (asyncio.TimeoutError, OSError):
        return False


async def _probe_http_banner(ip: str, port: int, timeout: float) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"http://{ip}:{port}/", follow_redirects=False)
            server = resp.headers.get("server") or resp.headers.get("Server")
            return server or f"HTTP {resp.status_code}"
    except (httpx.RequestError, Exception):
        return None


_BANNER_HINTS = {
    "hikvision": "Hikvision", "dahua": "Dahua", "axis": "Axis",
    "uniview": "Uniview", "reolink": "Reolink", "boa": "Generic (Boa httpd)",
}


def _guess_manufacturer_from_banner(banner: Optional[str]) -> Optional[str]:
    if not banner:
        return None
    lowered = banner.lower()
    for needle, brand in _BANNER_HINTS.items():
        if needle in lowered:
            return brand
    return None


async def sweep_host(ip: str, timeout: float = DEFAULT_PROBE_TIMEOUT) -> Optional[SweepResult]:
    open_ports = []
    for port in CAMERA_PORTS:
        if await _probe_port(ip, port, timeout):
            open_ports.append(port)
    if not open_ports:
        return None

    result = SweepResult(ip=ip, open_ports=open_ports)
    if 554 in open_ports:
        result.rtsp_responded = await _probe_rtsp_options(ip, 554, timeout)
    for http_port in (80, 8000, 8899, 2020):
        if http_port in open_ports:
            result.http_banner = await _probe_http_banner(ip, http_port, timeout)
            if result.http_banner:
                break
    result.guessed_manufacturer = _guess_manufacturer_from_banner(result.http_banner)
    # A camera-shaped host: RTSP responded, or an HTTP banner hinted at a
    # known brand. Bare open ports with no protocol confirmation are too
    # weak a signal on their own — lots of non-camera devices have port 80 open.
    if not result.rtsp_responded and not result.guessed_manufacturer:
        return None
    return result


async def sweep_subnet(
    cidr: str,
    force: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
    on_progress=None,
    should_cancel=None,
) -> list:
    hosts = parse_cidr(cidr, force=force)
    semaphore = asyncio.Semaphore(concurrency)
    results = []
    scanned = 0
    lock = asyncio.Lock()

    async def worker(ip):
        nonlocal scanned
        if should_cancel and should_cancel():
            return
        async with semaphore:
            # Re-checked here, not just on worker creation: all `len(hosts)`
            # workers are scheduled via gather() up front, so by the time a
            # cancel flag flips almost every worker has already passed the
            # first check and is only waiting on the semaphore. Checking
            # again right before the actual probe is what makes cancel take
            # effect promptly instead of draining the whole queue anyway.
            if should_cancel and should_cancel():
                return
            r = await sweep_host(ip, timeout=timeout)
        async with lock:
            scanned += 1
            if r:
                results.append(r)
            if on_progress:
                on_progress(scanned, len(hosts))

    await asyncio.gather(*(worker(ip) for ip in hosts))
    return results
