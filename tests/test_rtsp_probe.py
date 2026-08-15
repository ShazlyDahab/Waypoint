"""Tests for the RTSP OPTIONS probe's failure classification. Everything
runs against a local mock TCP server (or a closed port) — no test depends
on a real camera being reachable."""

import socket
import threading
import time

import pytest

from admin_portal.api.camera_network import _rtsp_options_probe


def _serve_once(port_holder, response_bytes, delay=0):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port_holder.append(srv.getsockname()[1])

    def run():
        conn, _ = srv.accept()
        conn.recv(4096)
        if delay:
            time.sleep(delay)
        if response_bytes:
            conn.sendall(response_bytes)
        conn.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()


def _wait_for_port(port_holder, timeout=2):
    start = time.time()
    while not port_holder and time.time() - start < timeout:
        time.sleep(0.01)
    return port_holder[0]


def test_success_response_classified_ok():
    port_holder = []
    _serve_once(port_holder, b"RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n")
    port = _wait_for_port(port_holder)
    result = _rtsp_options_probe("127.0.0.1", port, "user", "pass", "/stream1")
    assert result == {"ok": True, "reason": "ok", "detail": "RTSP/1.0 200 OK"}


def test_auth_challenge_classified_as_auth_rejected():
    port_holder = []
    _serve_once(port_holder, b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n\r\n")
    port = _wait_for_port(port_holder)
    result = _rtsp_options_probe("127.0.0.1", port, "user", "wrongpass", "/stream1")
    assert result["ok"] is False
    assert result["reason"] == "auth rejected"


def test_closed_port_classified_as_unreachable():
    # Bind-and-close to get a genuinely closed port on this host, rather
    # than guessing at an unused one.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    closed_port = s.getsockname()[1]
    s.close()

    result = _rtsp_options_probe("127.0.0.1", closed_port, "user", "pass", "/stream1")
    assert result["ok"] is False
    assert result["reason"] == "unreachable"


def test_slow_server_classified_as_timeout():
    port_holder = []
    _serve_once(port_holder, b"RTSP/1.0 200 OK\r\n\r\n", delay=2)
    port = _wait_for_port(port_holder)
    result = _rtsp_options_probe("127.0.0.1", port, "user", "pass", "/stream1", timeout=0.3)
    assert result["ok"] is False
    assert result["reason"] == "timeout"


def test_garbage_response_classified_as_unexpected():
    port_holder = []
    _serve_once(port_holder, b"not an rtsp response at all\r\n")
    port = _wait_for_port(port_holder)
    result = _rtsp_options_probe("127.0.0.1", port, "user", "pass", "/stream1")
    assert result["ok"] is False
    assert result["reason"] == "unexpected response"
