"""账号书架真实协议形状的离线回归；仅替换 requests.Session.get。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from fastapi.testclient import TestClient

from zhihu_downloader.app import create_app
from zhihu_downloader.auth import cookies
from zhihu_downloader.engine.account_shelf import normalize_book
from zhihu_downloader.engine.client import ZhihuClient
from zhihu_downloader.shelf.shelf import Shelf


def column(book_id: str, number: int = 123) -> dict:
    return {"id": book_id, "title": "离线测试小说", "property_type": "paid_column",
            "business_url": f"https://www.zhihu.com/market/paid_column/{number}?share_token=PRIVATE",
            "is_purchased": False}


def page(rows: list, offset: int = 0, next_offset: int | None = None) -> dict:
    return {"data": rows, "pagination": {
        "offset": offset, "limit": 10, "totals": len(rows), "is_end": next_offset is None,
        "next": f"https://api.zhihu.com/pluton/shelves?limit=10&offset={next_offset}",
    }}


@pytest.fixture()
def account_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cookie_file = tmp_path / "cookies.json"
    cookies.save({"z_c0": "OFFLINE_COOKIE", "d_c0": "OFFLINE_SIGN"}, cookie_file)
    state = SimpleNamespace(
        pages={0: page([column("first"), {"id": "work", "title": "新版故事", "producer": "work",
                                       "property_type": "short_story"}], next_offset=10),
               10: page([column("second", 456)], offset=10)},
        calls=[], sent_cookies=[], error_status=None, me={"id": "offline-user"}, on_shelf=None,
    )

    def get(session, url, **kwargs):
        state.calls.append(url)
        state.sent_cookies.append(session.cookies.get("z_c0", domain=".zhihu.com"))
        parsed = urlparse(url)
        response = requests.Response()
        response.status_code = 200
        response.url = url
        if parsed.path == "/api/v4/me":
            body = json.dumps(state.me)
            response.status_code = state.error_status or 200
        elif parsed.path == "/pluton/shelves":
            offset = int(parse_qs(parsed.query).get("offset", [0])[0])
            value = state.pages[offset]
            body = value if isinstance(value, str) else json.dumps(value)
            if state.on_shelf:
                state.on_shelf()
        elif "/section/" in parsed.path:
            body = '<html><title>测试章节</title><div class="RichText"><p>测试正文，包含足够长的可阅读文字。</p></div></html>'
        elif parsed.path.startswith("/market/paid_column/"):
            body = f'<html><title>离线测试小说</title><a href="{parsed.path}/section/1">第一章</a></html>'
        else:
            raise AssertionError("Unexpected external request")
        response._content = body.encode("utf-8")
        response.encoding = "utf-8"
        return response

    monkeypatch.setattr(requests.Session, "get", get)
    client = ZhihuClient(cookie_file=cookie_file, rate_limit=0, retries=0)
    app = create_app(client=client, shelf=Shelf(tmp_path / "shelf.json"), output_dir=tmp_path / "output")
    with TestClient(app) as http:
        yield SimpleNamespace(http=http, state=state, app=app, cookie_file=cookie_file, root=tmp_path)


def test_list_normalization_and_pagination(account_env):
    env = account_env
    first = env.http.get("/api/account-shelf")
    assert first.status_code == 200
    body = first.json()
    assert body["next_offset"] == 10
    assert body["books"][0]["supported"] is True
    assert body["books"][0]["url"] == "https://www.zhihu.com/market/paid_column/123"
    assert body["books"][1]["supported"] is False
    assert "新版短故事" in body["books"][1]["unsupported_reason"]
    assert "PRIVATE" not in first.text and "OFFLINE_COOKIE" not in first.text
    assert first.headers["Cache-Control"] == "no-store"
    second = env.http.get("/api/account-shelf?offset=10").json()
    assert second["next_offset"] is None
    assert second["books"][0]["id"] == "second"
    assert body["session_id"] == second["session_id"]


def test_empty_shelf(account_env):
    account_env.state.pages[0] = page([])
    response = account_env.http.get("/api/account-shelf")
    assert response.status_code == 200
    assert response.json()["books"] == [] and response.json()["total"] == 0


def test_missing_login_does_not_request_remote(account_env):
    account_env.cookie_file.unlink()
    assert account_env.http.get("/api/account-shelf").status_code == 401
    assert account_env.state.calls == []


@pytest.mark.parametrize("me,status", [({}, None), ({"error": {"code": 10003}}, None), ({}, 401)])
def test_expired_login_is_not_empty_shelf(account_env, me, status):
    account_env.state.me = me
    account_env.state.error_status = status
    response = account_env.http.get("/api/account-shelf")
    assert response.status_code == 401
    assert "登录" in response.json()["detail"]


def test_blocked_request_is_reported(account_env):
    account_env.state.error_status = 403
    response = account_env.http.get("/api/account-shelf")
    assert response.status_code == 502
    assert "403" in response.json()["detail"]


@pytest.mark.parametrize("broken", ["<html>login</html>", [], {}, {"data": [], "pagination": {}}])
def test_invalid_remote_response_is_not_empty_shelf(account_env, broken):
    account_env.state.pages[0] = broken
    response = account_env.http.get("/api/account-shelf")
    assert response.status_code == 502


@pytest.mark.parametrize("changes", [
    {"next": "https://evil.invalid/pluton/shelves?offset=10"},
    {"next": "https://api.zhihu.com/pluton/shelves?offset=0"},
    {"next": "https://api.zhihu.com/pluton/shelves?offset=-1"},
    {"next": "https://api.zhihu.com/pluton/shelves?offset=1.5"},
    {"next": None}, {"offset": 10}, {"totals": True}, {"is_end": "false"},
])
def test_invalid_pagination_does_not_follow_remote_url(account_env, changes):
    account_env.state.pages[0]["pagination"].update(changes)
    assert account_env.http.get("/api/account-shelf").status_code == 502
    assert len(account_env.state.calls) == 2


def test_page_deduplicates_records(account_env):
    account_env.state.pages[0] = page([column("first"), column("first")])
    assert len(account_env.http.get("/api/account-shelf").json()["books"]) == 1


@pytest.mark.parametrize("query", ["offset=-1", "offset=1000001", "limit=0", "limit=51"])
def test_invalid_query_is_rejected_before_requests(account_env, query):
    assert account_env.http.get("/api/account-shelf?" + query).status_code == 422
    assert account_env.state.calls == []


def test_session_rotates_and_prevents_stale_account_download(account_env):
    env = account_env
    session = env.http.get("/api/cookies").headers["X-Account-Session"]
    assert session == env.http.get("/api/cookies").headers["X-Account-Session"]
    cookies.save({"z_c0": "NEW_ACCOUNT", "d_c0": "NEW_SIGN"}, env.cookie_file)
    assert session != env.http.get("/api/cookies").headers["X-Account-Session"]
    response = env.http.post("/api/download", json={"url": column("first")["business_url"],
                                                 "account_session": session})
    assert response.status_code == 409
    assert not env.app.state.zhihu.tasks.list()
    assert env.http.get("/api/account-shelf").status_code == 200
    assert set(env.state.sent_cookies) == {"NEW_ACCOUNT"}


def test_account_change_during_fetch_drops_old_results(account_env):
    env = account_env
    env.state.on_shelf = lambda: cookies.save({"z_c0": "CHANGED", "d_c0": "SIGN"}, env.cookie_file)
    assert env.http.get("/api/account-shelf").status_code == 409


def test_selected_download_does_not_merge_previous_accounts_memory_cookies(account_env):
    env = account_env
    # 模拟另一个页签或进程已更新 Cookie 文件，应用基础客户端仍保留旧内存值。
    cookies.save({"z_c0": "NEW_ACCOUNT", "d_c0": "NEW_SIGN"}, env.cookie_file)
    listing = env.http.get("/api/account-shelf").json()
    result = env.http.post("/api/download", json={
        "url": listing["books"][0]["url"], "format": "txt", "rate_limit": 0,
        "account_session": listing["session_id"],
    })
    task = env.app.state.zhihu.tasks.get(result.json()["task_id"])
    assert task.finished.wait(20) and task.status == "done"
    assert set(env.state.sent_cookies) == {"NEW_ACCOUNT"}


@pytest.mark.parametrize("fmt", ["txt", "md", "epub"])
def test_selected_book_uses_real_download_pipeline_and_local_shelf(account_env, fmt):
    env = account_env
    listing = env.http.get("/api/account-shelf").json()
    for book in (listing["books"][0], env.http.get("/api/account-shelf?offset=10").json()["books"][0]):
        result = env.http.post("/api/download", json={
            "url": book["url"], "format": fmt, "account_session": listing["session_id"], "rate_limit": 0,
        })
        assert result.status_code == 200
        task = env.app.state.zhihu.tasks.get(result.json()["task_id"])
        assert task.finished.wait(20)
        assert task.status == "done", task.error
        for filename, path in task.files.items():
            assert env.http.get(f"/api/files/{task.id}/{filename}").status_code == 200
            if fmt == "epub":
                with zipfile.ZipFile(path) as archive:
                    assert any("测试正文" in archive.read(name).decode("utf-8")
                               for name in archive.namelist() if name.endswith(".xhtml"))
            else:
                assert "测试正文" in Path(path).read_text(encoding="utf-8-sig")
    assert len(env.http.get("/api/shelf").json()) == 2


@pytest.mark.parametrize("url", [
    "https://www.zhihu.com.evil.invalid/market/paid_column/123",
    "https://evil.invalid@www.zhihu.com/market/paid_column/123",
    "http://127.0.0.1\\@www.zhihu.com/market/paid_column/123",
    "javascript:alert(1)", "zhihu://paid_column/123", "?catalog_type=paid_column",
])
def test_untrusted_or_native_links_are_not_downloadable(url):
    book = normalize_book({"id": "test", "business_url": url})
    assert not book.supported and not book.url and not book.source_url


def test_live_and_app_only_have_clear_reasons():
    assert "Live" in normalize_book({"id": "live", "property_type": "Live"}).unsupported_reason
    assert "App" in normalize_book({"id": "app", "business_url":
                                   "https://story.zhihu.com/manuscript/paid_column/123"}).unsupported_reason
