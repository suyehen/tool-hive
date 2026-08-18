"""入口校验中间件测试。"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from toolhive.api.ingress import IngressMiddleware
from toolhive.config import NetworkSettings


def _build_app(network: NetworkSettings) -> Starlette:
    app = Starlette()
    app.add_middleware(IngressMiddleware, network=network)

    async def ping(request):
        return JSONResponse(
            {"ok": True, "client_ip": getattr(request.state, "client_ip", None)},
        )

    async def health(request):
        return JSONResponse({"ok": True})

    app.router.add_route("/api/admin/ping", ping)
    app.router.add_route("/health", health)
    return app


class TestIngressMiddleware:
    def test_trusted_proxy_with_ingress_ok(self) -> None:
        app = _build_app(NetworkSettings())
        client = TestClient(app, client=("127.0.0.1", 50000))
        resp = client.get(
            "/api/admin/ping",
            headers={
                "X-ToolHive-Ingress": "admin",
                "X-ToolHive-Client-IP": "10.0.0.5",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["client_ip"] == "10.0.0.5"

    def test_trusted_proxy_missing_ingress_rejected(self) -> None:
        app = _build_app(NetworkSettings())
        client = TestClient(app, client=("127.0.0.1", 50000))
        resp = client.get("/api/admin/ping")
        assert resp.status_code == 403

    def test_wrong_ingress_rejected(self) -> None:
        app = _build_app(NetworkSettings())
        client = TestClient(app, client=("127.0.0.1", 50000))
        resp = client.get(
            "/api/admin/ping",
            headers={"X-ToolHive-Ingress": "runtime"},
        )
        assert resp.status_code == 403

    def test_untrusted_source_rejected(self) -> None:
        app = _build_app(NetworkSettings())
        client = TestClient(app, client=("10.0.0.9", 50000))
        resp = client.get(
            "/api/admin/ping",
            headers={"X-ToolHive-Ingress": "admin"},
        )
        assert resp.status_code == 403

    def test_loopback_direct_allowed_when_enabled(self) -> None:
        app = _build_app(NetworkSettings(allow_loopback_direct=True))
        client = TestClient(app, client=("127.0.0.1", 50000))
        resp = client.get("/api/admin/ping")
        assert resp.status_code == 200
        assert resp.json()["client_ip"] == "127.0.0.1"

    def test_invalid_client_ip_rejected(self) -> None:
        app = _build_app(NetworkSettings())
        client = TestClient(app, client=("127.0.0.1", 50000))
        resp = client.get(
            "/api/admin/ping",
            headers={
                "X-ToolHive-Ingress": "admin",
                "X-ToolHive-Client-IP": "bad",
            },
        )
        assert resp.status_code == 403

    def test_health_no_ingress_required(self) -> None:
        app = _build_app(NetworkSettings())
        client = TestClient(app, client=("127.0.0.1", 50000))
        resp = client.get("/health")
        assert resp.status_code == 200
