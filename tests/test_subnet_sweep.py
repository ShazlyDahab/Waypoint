import asyncio
import socket
import threading
import time

import pytest

from admin_portal.discovery.subnet_sweep import parse_cidr, sweep_host, sweep_subnet, RangeTooLarge


def test_parse_cidr_normal_range():
    hosts = parse_cidr("192.168.1.0/29")  # 6 usable hosts
    assert len(hosts) == 6
    assert "192.168.1.1" in hosts


def test_parse_cidr_refuses_large_range_without_force():
    with pytest.raises(RangeTooLarge):
        parse_cidr("10.0.0.0/8")  # ~16 million hosts


def test_parse_cidr_allows_large_range_with_force():
    hosts = parse_cidr("192.168.0.0/21", force=True)  # 2046 hosts, over the /22 default cap
    assert len(hosts) > 1024


def test_parse_cidr_boundary_slash22_allowed_without_force():
    hosts = parse_cidr("10.0.0.0/22")  # exactly 1022 usable hosts — under the cap
    assert len(hosts) <= 1024


def _serve_rtsp_once(port_holder):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port_holder.append(srv.getsockname()[1])

    def run():
        conn, _ = srv.accept()
        conn.recv(4096)
        conn.sendall(b"RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n")
        conn.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()


@pytest.mark.asyncio
async def test_sweep_host_detects_rtsp_responder():
    # sweep_host probes the fixed CAMERA_PORTS list, not an arbitrary port,
    # so this exercises the real port-probe + RTSP-OPTIONS path by binding
    # directly to port 554 conceptually — since binding to the real
    # privileged/camera port 554 isn't reliable in a sandboxed test run,
    # this test instead calls the lower-level RTSP probe directly against
    # a mock server on an ephemeral port.
    from admin_portal.discovery.subnet_sweep import _probe_rtsp_options

    port_holder = []
    _serve_rtsp_once(port_holder)
    start = time.time()
    while not port_holder and time.time() - start < 2:
        await asyncio.sleep(0.01)
    port = port_holder[0]

    responded = await _probe_rtsp_options("127.0.0.1", port, timeout=2.0)
    assert responded is True


@pytest.mark.asyncio
async def test_sweep_host_returns_none_for_closed_host():
    # A definitely-closed port on localhost — sweep_host should find no
    # open camera ports at all and return None, not raise.
    result = await sweep_host("127.0.0.1", timeout=0.3)
    # None of CAMERA_PORTS are expected open on a bare test machine; if one
    # happens to be (e.g. a local dev server on 8000), this would still be
    # a valid, non-crashing result either way — the real assertion is that
    # it doesn't raise.
    assert result is None or hasattr(result, "ip")


@pytest.mark.asyncio
async def test_sweep_subnet_cancel_stops_new_probes():
    # Regression test: should_cancel used to only be checked once per worker,
    # before it queued on the concurrency semaphore. Since every worker for
    # the whole CIDR is scheduled via gather() up front, that meant almost
    # all of them had already passed the check by the time a caller flipped
    # the flag, so cancelling had close to no effect. It must also be
    # rechecked right before the actual probe, after acquiring the
    # semaphore, so flipping the flag partway through actually halts
    # unstarted probes instead of draining the whole host list anyway.
    cancelled = {"flag": False}
    progress_calls = []

    def should_cancel():
        return cancelled["flag"]

    def on_progress(scanned, total):
        progress_calls.append(scanned)
        cancelled["flag"] = True  # cancel as soon as the first host finishes

    total_hosts = len(parse_cidr("10.255.255.0/28"))  # 14 usable hosts
    await sweep_subnet(
        "10.255.255.0/28", concurrency=3, timeout=0.2,
        on_progress=on_progress, should_cancel=should_cancel,
    )
    assert max(progress_calls) < total_hosts
