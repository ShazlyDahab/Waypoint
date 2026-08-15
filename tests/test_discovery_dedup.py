from admin_portal.discovery.dedup import match_existing_camera

EXISTING = [
    {"camera_id": "entrance_cam", "mac": "AA:BB:CC:DD:EE:01", "serial": "SN001", "ip": "192.168.1.50"},
    {"camera_id": "checkout_cam", "mac": "AA:BB:CC:DD:EE:02", "serial": "SN002", "ip": "192.168.1.51"},
]


def test_mac_match_same_ip_no_change_flagged():
    cam_id, reason, ip_changed = match_existing_camera(
        "AA:BB:CC:DD:EE:01", None, "192.168.1.50", EXISTING
    )
    assert (cam_id, reason, ip_changed) == ("entrance_cam", "mac", False)


def test_mac_match_is_case_insensitive():
    cam_id, reason, _ = match_existing_camera("aa:bb:cc:dd:ee:01", None, None, EXISTING)
    assert (cam_id, reason) == ("entrance_cam", "mac")


def test_mac_match_with_different_ip_flags_ip_changed():
    # The core "DHCP lease renewed" scenario: same camera, new IP.
    cam_id, reason, ip_changed = match_existing_camera(
        "AA:BB:CC:DD:EE:01", None, "192.168.1.99", EXISTING
    )
    assert (cam_id, reason, ip_changed) == ("entrance_cam", "mac", True)


def test_serial_match_when_no_mac_available():
    cam_id, reason, ip_changed = match_existing_camera(None, "SN002", "192.168.1.51", EXISTING)
    assert (cam_id, reason, ip_changed) == ("checkout_cam", "serial", False)


def test_serial_match_with_ip_change():
    cam_id, reason, ip_changed = match_existing_camera(None, "SN002", "10.0.0.5", EXISTING)
    assert (cam_id, reason, ip_changed) == ("checkout_cam", "serial", True)


def test_mac_takes_priority_over_serial():
    # A device reporting a mac matching one camera but a serial matching a
    # different one (bad data, or the wrong device) — mac wins per the
    # documented priority order.
    cam_id, reason, _ = match_existing_camera("AA:BB:CC:DD:EE:01", "SN002", None, EXISTING)
    assert (cam_id, reason) == ("entrance_cam", "mac")


def test_falls_back_to_ip_when_no_mac_or_serial():
    cam_id, reason, ip_changed = match_existing_camera(None, None, "192.168.1.51", EXISTING)
    assert (cam_id, reason, ip_changed) == ("checkout_cam", "ip", False)


def test_ip_only_match_never_flags_ip_changed():
    # There's nothing to compare against for an IP-only match — flagging a
    # change here would be nonsensical.
    cam_id, reason, ip_changed = match_existing_camera(None, None, "192.168.1.50", EXISTING)
    assert ip_changed is False


def test_no_match_returns_none():
    cam_id, reason, ip_changed = match_existing_camera(
        "FF:FF:FF:FF:FF:FF", "UNKNOWN", "10.10.10.10", EXISTING
    )
    assert (cam_id, reason, ip_changed) == (None, None, False)


def test_empty_existing_list():
    result = match_existing_camera("AA:BB:CC:DD:EE:01", "SN001", "192.168.1.50", [])
    assert result == (None, None, False)


def test_all_none_inputs_no_match():
    assert match_existing_camera(None, None, None, EXISTING) == (None, None, False)
