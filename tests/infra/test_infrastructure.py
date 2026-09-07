from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("DB_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "infra-test-secret")

from backend import main


ROOT = Path(__file__).resolve().parents[2]


def test_compose_has_full_healthy_dependency_graph() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    for service in ("backend", "bot", "frontend", "nginx", "postgres", "redis"):
        assert f"\n  {service}:\n" in compose
    assert compose.count("healthcheck:") >= 6
    assert compose.count("condition: service_healthy") >= 7
    assert "VITE_API_BASE_URL: ${VITE_API_BASE_URL:-http://localhost/api}" in compose


def test_https_overlay_and_nginx_routes_are_present() -> None:
    overlay = (ROOT / "scripts/deploy/docker-compose.https.yml").read_text()
    http_config = (ROOT / "nginx/default.conf.template").read_text()
    https_config = (ROOT / "nginx/https.conf.template").read_text()
    assert "${NGINX_HTTPS_PORT:-443}:443" in overlay
    assert "nginx/https.conf.template" in overlay
    for route in ("location /api/", "location /ws/", "location /"):
        assert route in http_config
        assert route in https_config
    assert "proxy_set_header Upgrade $http_upgrade" in https_config
    assert "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" in https_config

    issue_script = (ROOT / "scripts/deploy/issue_certificate.sh").read_text()
    renew_script = (ROOT / "scripts/deploy/renew_certificate.sh").read_text()
    assert "certonly" in issue_script
    assert "certbot renew" in renew_script
    assert "nginx -s reload" in renew_script


def test_health_reports_dependency_readiness(monkeypatch) -> None:
    monkeypatch.setattr(main, "_postgres_ready", lambda: True)
    monkeypatch.setattr(main, "_redis_ready", lambda: True)
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"postgres": True, "redis": True},
        "demo_mode": False,
    }

    monkeypatch.setattr(main, "_redis_ready", lambda: False)
    response = TestClient(main.app).get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
