import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from server.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_presets(client):
    data = client.get("/api/presets").json()
    assert [p["level"] for p in data["presets"]] == [1, 2, 3, 4, 5]


def test_create_and_fetch(client):
    r = client.post("/api/puzzle", json={"level": 1, "seed": 5})
    assert r.status_code == 200
    p = r.json()
    assert p["size"] == 5 and p["seed"] == 5
    assert client.get(f"/api/puzzle/{p['id']}").json()["grid"] == p["grid"]
    puz = client.get(f"/api/puzzle/{p['id']}/puz")
    assert puz.status_code == 200 and puz.content[2:14] == b"ACROSS&DOWN\0"
    page = client.get(f"/api/puzzle/{p['id']}/print")
    assert page.status_code == 200 and "<table>" in page.text


def test_errors(client):
    assert client.get("/api/puzzle/nope").status_code == 404
    assert client.post("/api/puzzle", json={"level": 9}).status_code == 422
    assert client.post("/api/puzzle", json={"level": 3, "size": 8}).status_code == 422
    assert client.post("/api/puzzle", json={"level": 3, "aids": ["x"]}).status_code == 422


def test_static_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "Procedural Crosswords" in r.text
    assert client.get("/app.js").status_code == 200
