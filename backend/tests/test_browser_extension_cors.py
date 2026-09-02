from fastapi.testclient import TestClient

from app.main import app


def _preflight(origin: str):
    return TestClient(app).options(
        "/api/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-mosael-client",
        },
    )


def test_chrome_extension_can_call_the_local_api_after_preflight() -> None:
    origin = f"chrome-extension://{'a' * 32}"

    response = _preflight(origin)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_an_arbitrary_web_page_is_not_added_to_the_api_trust_boundary() -> None:
    response = _preflight("https://attacker.example")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
