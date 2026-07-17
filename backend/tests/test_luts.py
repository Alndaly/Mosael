from __future__ import annotations

from tests.util import fresh_client

CUBE = ("TITLE \"Test\"\nLUT_3D_SIZE 2\n" + "\n".join(["0.0 0.0 0.0"] * 8)).encode("utf-8")


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_lut_upload_list_delete() -> None:
    client = fresh_client()
    ws = _workspace(client)

    res = client.post(
        "/api/luts",
        data={"workspace_id": ws, "name": "My Look"},
        files={"file": ("look.cube", CUBE, "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    lut = res.json()
    assert lut["name"] == "My Look" and lut["original_filename"] == "look.cube" and lut["size"] == len(CUBE)

    listing = client.get("/api/luts", params={"workspace_id": ws}).json()
    assert [item["id"] for item in listing] == [lut["id"]]

    renamed = client.patch(f"/api/luts/{lut['id']}", json={"name": "Renamed"}).json()
    assert renamed["name"] == "Renamed"

    assert client.delete(f"/api/luts/{lut['id']}").status_code == 204
    assert client.get("/api/luts", params={"workspace_id": ws}).json() == []


def test_lut_rejects_non_cube() -> None:
    client = fresh_client()
    ws = _workspace(client)
    res = client.post(
        "/api/luts",
        data={"workspace_id": ws},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 422


def test_lut_rejects_invalid_cube() -> None:
    client = fresh_client()
    ws = _workspace(client)
    res = client.post(
        "/api/luts",
        data={"workspace_id": ws},
        files={"file": ("bad.cube", b"no size marker here\n0 0 0", "application/octet-stream")},
    )
    assert res.status_code == 422
