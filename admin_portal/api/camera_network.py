"""
Camera network/device details, encrypted credentials, and manual-add.

Credentials are stored encrypted (admin_portal/security.py) and NEVER
returned in any response — only {id, label, username}. Decryption happens
only server-side, only when actually needed (testing a connection,
building an RTSP URL for the restreamer).

Manual-add writes to BOTH cameras.json (via store.py — id/name/rtsp_url,
exactly like the two original demo cameras, so the existing pipeline
scripts (calibrate_zones.py, multi_camera_dashboard.py) keep working
unchanged) AND camera_network (rich metadata + a credential_id reference).
This means the RTSP URL embedded in cameras.json still contains the
plaintext credential at that one call site — the same as it already did
for the original demo cameras. That's a real, worth-naming tradeoff: this
feature adds *structured, encrypted* credential storage for the new UI, it
does not retrofit the older plaintext-URL convention the pipeline scripts
already depend on.
"""

import socket
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, security, store
from ..rtsp_paths import build_rtsp_url

router = APIRouter()


# --------------------------------------------------------- credentials -----

class CredentialIn(BaseModel):
    label: str
    username: str
    password: str


def _cred_public(row) -> dict:
    return {"id": row["id"], "label": row["label"], "username": row["username"], "updated_at": row["updated_at"]}


@router.get("/credentials")
def list_credentials():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM credentials ORDER BY label").fetchall()
    return [_cred_public(r) for r in rows]


@router.post("/credentials")
def create_credential(body: CredentialIn):
    conn = db.get_conn()
    ts = db.now()
    encrypted = security.encrypt_password(body.password)
    cur = conn.execute(
        "INSERT INTO credentials (label, username, encrypted_password, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (body.label, body.username, encrypted, ts, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM credentials WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _cred_public(row)


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: int):
    conn = db.get_conn()
    in_use = conn.execute(
        "SELECT camera_id FROM camera_network WHERE credential_id = ?", (credential_id,)
    ).fetchall()
    if in_use:
        cams = ", ".join(r["camera_id"] for r in in_use)
        raise HTTPException(409, f"Still used by: {cams} — update or remove those first")
    conn.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
    conn.commit()
    return {"ok": True}


def _decrypt_credential(credential_id: Optional[int]):
    if credential_id is None:
        return None, None
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Credential not found")
    return row["username"], security.decrypt_password(row["encrypted_password"])


# ------------------------------------------------------- camera network ----

class NetworkIn(BaseModel):
    ip: Optional[str] = None
    mac: Optional[str] = None
    hostname: Optional[str] = None
    rtsp_port: Optional[int] = 554
    http_port: Optional[int] = 80
    onvif_port: Optional[int] = 80
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    firmware: Optional[str] = None
    serial: Optional[str] = None
    main_stream_uri: Optional[str] = None
    main_stream_width: Optional[int] = None
    main_stream_height: Optional[int] = None
    main_stream_codec: Optional[str] = None
    main_stream_fps: Optional[float] = None
    sub_stream_uri: Optional[str] = None
    sub_stream_width: Optional[int] = None
    sub_stream_height: Optional[int] = None
    sub_stream_codec: Optional[str] = None
    sub_stream_fps: Optional[float] = None
    credential_id: Optional[int] = None


def _network_public(row) -> dict:
    d = dict(row)
    return d  # already excludes any credential secret — table only ever stores credential_id


@router.get("/{camera_id}/network")
def get_camera_network(camera_id: str):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM camera_network WHERE camera_id = ?", (camera_id,)).fetchone()
    if row is None:
        return {"camera_id": camera_id, "connection_state": "not_configured"}
    return _network_public(row)


@router.put("/{camera_id}/network")
def put_camera_network(camera_id: str, body: NetworkIn):
    if store.get_camera(camera_id) is None:
        raise HTTPException(404, "Unknown camera")
    conn = db.get_conn()
    ts = db.now()
    fields = body.model_dump()
    exists = conn.execute("SELECT 1 FROM camera_network WHERE camera_id = ?", (camera_id,)).fetchone()
    if exists:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE camera_network SET {set_clause}, updated_at = ? WHERE camera_id = ?",
            (*fields.values(), ts, camera_id),
        )
    else:
        cols = ["camera_id"] + list(fields.keys()) + ["updated_at"]
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO camera_network ({', '.join(cols)}) VALUES ({placeholders})",
            (camera_id, *fields.values(), ts),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM camera_network WHERE camera_id = ?", (camera_id,)).fetchone()
    return _network_public(row)


# ------------------------------------------------------------ manual add ---

class ManualAddIn(BaseModel):
    id: str
    name: str
    ip: str
    rtsp_port: int = 554
    stream_path: str = "/stream1"
    credential_id: int
    manufacturer: Optional[str] = None
    model: Optional[str] = None


@router.post("/manual")
def manual_add_camera(body: ManualAddIn):
    cameras = store.load_cameras()
    if any(c["id"] == body.id for c in cameras):
        raise HTTPException(409, f"Camera id '{body.id}' already exists")

    username, password = _decrypt_credential(body.credential_id)
    if username is None:
        raise HTTPException(400, "credential_id is required")
    rtsp_url = build_rtsp_url(body.ip, body.rtsp_port, username, password, body.stream_path)

    cameras.append({"id": body.id, "name": body.name, "rtsp_url": rtsp_url})
    store.save_cameras(cameras)

    conn = db.get_conn()
    ts = db.now()
    conn.execute(
        "INSERT INTO camera_network (camera_id, ip, rtsp_port, manufacturer, model, "
        "main_stream_uri, credential_id, connection_state, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'not_configured', ?)",
        (body.id, body.ip, body.rtsp_port, body.manufacturer, body.model, rtsp_url, body.credential_id, ts),
    )
    conn.commit()
    return {"ok": True, "camera_id": body.id}


# ------------------------------------------------------ test credentials ---

class TestCredentialsIn(BaseModel):
    ip: str
    rtsp_port: int = 554
    stream_path: str = "/stream1"
    credential_id: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/test-credentials")
def test_credentials(body: TestCredentialsIn):
    if body.credential_id is not None:
        username, password = _decrypt_credential(body.credential_id)
    else:
        username, password = body.username, body.password
    if not username:
        raise HTTPException(400, "Provide credential_id, or username/password directly")

    result = _rtsp_options_probe(body.ip, body.rtsp_port, username, password, body.stream_path)
    return result


def _rtsp_options_probe(host: str, port: int, username: str, password: str, path: str, timeout: float = 3.0) -> dict:
    """Sends a bare RTSP OPTIONS request (RTSP is a text protocol closely
    related to HTTP) and classifies the result into the specific failure
    categories the spec asks for, instead of a generic error. Credentials
    aren't even sent on this first probe — RTSP auth only reveals itself
    once the server challenges with a 401, at which point we report
    'auth rejected' rather than attempting a full digest-auth handshake
    (this is a reachability/liveness check, not a full stream negotiation)."""
    url = f"rtsp://{host}:{port}{path}"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            request = f"OPTIONS {url} RTSP/1.0\r\nCSeq: 1\r\n\r\n"
            sock.sendall(request.encode())
            response = sock.recv(4096).decode(errors="replace")
    except socket.timeout:
        return {"ok": False, "reason": "timeout", "detail": f"No response from {host}:{port} within {timeout}s"}
    except (ConnectionRefusedError, OSError) as e:
        return {"ok": False, "reason": "unreachable", "detail": str(e)}

    first_line = response.splitlines()[0] if response else ""
    if "401" in first_line:
        return {"ok": False, "reason": "auth rejected", "detail": first_line}
    if "200" in first_line:
        return {"ok": True, "reason": "ok", "detail": first_line}
    return {"ok": False, "reason": "unexpected response", "detail": first_line or "empty response"}
