from admin_portal.rtsp_paths import guess_rtsp_paths, build_rtsp_url, BRAND_PATHS


def test_known_brand_exact_match():
    assert guess_rtsp_paths("Hikvision") == BRAND_PATHS["hikvision"]


def test_case_and_whitespace_insensitive():
    assert guess_rtsp_paths("  DAHUA  ") == BRAND_PATHS["dahua"]


def test_matches_substring_within_full_onvif_string():
    # real ONVIF GetDeviceInformation Manufacturer fields are often verbose
    assert guess_rtsp_paths("AXIS Communications AB") == BRAND_PATHS["axis"]


def test_sub_brand_alias_maps_to_parent():
    assert guess_rtsp_paths("IMOU") == BRAND_PATHS["dahua"]


def test_unknown_manufacturer_falls_back_to_generic():
    assert guess_rtsp_paths("SomeRandomVendor Inc") == BRAND_PATHS["generic"]


def test_none_and_empty_fall_back_to_generic():
    assert guess_rtsp_paths(None) == BRAND_PATHS["generic"]
    assert guess_rtsp_paths("") == BRAND_PATHS["generic"]


def test_returned_dict_is_a_copy_not_shared_mutable_state():
    result = guess_rtsp_paths("hikvision")
    result["main"] = "corrupted"
    assert BRAND_PATHS["hikvision"]["main"] != "corrupted"


def test_build_rtsp_url_assembles_correctly():
    url = build_rtsp_url("192.168.1.50", 554, "admin", "s3cr3t", "/Streaming/Channels/101")
    assert url == "rtsp://admin:s3cr3t@192.168.1.50:554/Streaming/Channels/101"
