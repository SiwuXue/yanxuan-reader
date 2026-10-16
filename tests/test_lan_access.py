"""局域网访问验证只在离线 FastAPI 测试客户端中运行。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zhihu_downloader.app.lan_access import LAN_SESSION_COOKIE
from zhihu_downloader.app.server import create_app
from zhihu_downloader.engine.client import ZhihuClient
from zhihu_downloader.shelf.shelf import Shelf

LAN_HOST = "192.168.50.2"
PHONE_HOST = "192.168.50.20"
BASE_URL = f"http://{LAN_HOST}:3000"
LAN_ORIGIN = BASE_URL


@pytest.fixture()
def lan_app(tmp_path: Path):
    return create_app(
        client=ZhihuClient(cookie_file=tmp_path / "cookies.json", rate_limit=0),
        output_dir=tmp_path / "out",
        shelf=Shelf(path=tmp_path / "shelf.json"),
        lan_access_code="12345678",
        lan_hosts=(LAN_HOST,),
    )


def phone_client(app, phone_host: str = PHONE_HOST) -> TestClient:
    return TestClient(
        app,
        base_url=BASE_URL,
        client=(phone_host, 43123),
    )


def unlock(http: TestClient, code: str = "12345678"):
    return http.post(
        "/api/lan/unlock",
        json={"code": code},
        headers={"Origin": LAN_ORIGIN},
    )


def test_remote_clients_only_get_unlock_page_before_auth(lan_app) -> None:
    with phone_client(lan_app) as http:
        page = http.get("/")
        assert page.status_code == 200
        assert "连接盐选书房" in page.text
        assert "page-account" not in page.text
        assert http.get("/lan-unlock.css").status_code == 200
        assert http.get("/lan-unlock.js").status_code == 200

        for path in (
            "/style.css", "/app.js", "/api/health", "/api/cookies",
            "/api/tasks", "/api/account-shelf", "/api/tasks/unknown/events",
            "/api/files/unknown/book.epub",
        ):
            assert http.get(path).status_code == 401, path

        for path, payload in (
            ("/api/download", {"url": "https://www.zhihu.com/example"}),
            ("/api/cookies/import", {"raw": "z_c0=secret"}),
            ("/api/qrcode", {}),
        ):
            denied = http.post(path, json=payload)
            assert denied.status_code == 401, path


def test_valid_code_unlocks_session_and_same_origin_writes(lan_app) -> None:
    with phone_client(lan_app) as http:
        response = unlock(http)
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "max-age=" not in cookie
        assert LAN_SESSION_COOKIE in http.cookies

        assert "page-account" in http.get("/").text
        assert http.get("/api/health").status_code == 200
        assert http.get("/api/cookies").status_code == 200
        assert http.get("/api/tasks").status_code == 200

        same_origin = http.post(
            "/api/shelf/does-not-exist/update",
            json={},
            headers={"Origin": LAN_ORIGIN},
        )
        assert same_origin.status_code == 404

        cross_origin = http.post(
            "/api/shelf/does-not-exist/update",
            json={},
            headers={"Origin": "https://evil.example"},
        )
        assert cross_origin.status_code == 403

        missing_origin = http.post("/api/shelf/does-not-exist/update", json={})
        assert missing_origin.status_code == 403


def test_code_is_limited_per_client_after_five_failures(lan_app) -> None:
    with phone_client(lan_app) as http:
        for _ in range(4):
            assert unlock(http, "00000000").status_code == 401
        limited = unlock(http, "00000000")
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "300"
        assert unlock(http).status_code == 429

    # The same startup code can unlock another device in the same private network.
    with phone_client(lan_app, "192.168.50.21") as another_phone:
        assert unlock(another_phone).status_code == 200


def test_sessions_do_not_survive_a_new_server_process(tmp_path: Path) -> None:
    def make_app(code: str):
        return create_app(
            client=ZhihuClient(cookie_file=tmp_path / "cookies.json", rate_limit=0),
            output_dir=tmp_path / "out",
            shelf=Shelf(path=tmp_path / "shelf.json"),
            lan_access_code=code,
            lan_hosts=(LAN_HOST,),
        )

    with phone_client(make_app("12345678")) as first:
        assert unlock(first).status_code == 200
        session = first.cookies.get(LAN_SESSION_COOKIE)

    with phone_client(make_app("87654321")) as restarted:
        restarted.cookies.set(LAN_SESSION_COOKIE, session)
        assert restarted.get("/api/tasks").status_code == 401
        assert "连接盐选书房" in restarted.get("/").text


def test_non_private_clients_are_rejected(lan_app) -> None:
    with phone_client(lan_app, "198.51.100.25") as outside:
        assert outside.get("/").status_code == 403
