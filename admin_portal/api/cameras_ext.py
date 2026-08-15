"""Lightweight read-only camera list for the React app's sidebar. Deliberately
returns only id/name — never rtsp_url — even though this app has no auth
today, so a camera's embedded credentials don't end up in a browser response
that doesn't need them."""

from fastapi import APIRouter

from .. import store

router = APIRouter()


@router.get("")
def list_cameras():
    return [{"id": c["id"], "name": c.get("name") or c["id"]} for c in store.load_cameras()]
