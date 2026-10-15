"""知乎账号书架只读适配，不缓存登录态或书目，不修改远端书架。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from ..errors import AuthError, ParseError, ZhihuError
from ..types import AccountShelfBook, AccountShelfPage
from .client import _is_zhihu_target

if TYPE_CHECKING:
    from .client import ZhihuClient

ACCOUNT_SHELF_URL = "https://api.zhihu.com/pluton/shelves"
_COLUMN = re.compile(r"^/market/paid_column/\d+(?:/section/\d+)?/?$")
_ANSWER = re.compile(r"^/question/\d+/answer/\d+/?$")
_ARTICLE = re.compile(r"^/p/\d+/?$")


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError
    number = int(value)
    if number < 0 or str(number) != str(value):
        raise ValueError
    return number


def _json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ParseError("账号书架返回了非 JSON 数据，请稍后重试或重新登录。") from exc
    if not isinstance(data, dict):
        raise ParseError("账号书架数据结构发生变化，请更新程序后重试。")
    if data.get("error") or data.get("success") is False:
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if str(code) in {"100", "401", "10002", "10003", "10004"}:
            raise AuthError("知乎登录已失效，请重新扫码登录后刷新账号书架。")
        raise ZhihuError("知乎未能返回账号书架，请稍后重试；若持续失败，请重新登录。")
    return data


def _fetch_json(client: ZhihuClient, url: str) -> dict[str, Any]:
    try:
        return _json_object(client.fetch(url))
    except ZhihuError as exc:
        if "HTTP 401" in str(exc):
            raise AuthError("知乎登录已失效，请重新扫码登录后刷新账号书架。") from exc
        raise


def normalize_book(raw: dict[str, Any]) -> AccountShelfBook:
    """只采用明确提供的网页版 URL，不把新版 work ID 猜成 paid_column ID。"""
    book_id = str(raw.get("id") or raw.get("sku_id") or "")
    if not book_id:
        raise ParseError("账号书架条目缺少标识，无法可靠分页，请更新程序后重试。")
    kind = str(raw.get("property_type") or raw.get("producer") or "unknown")
    source = ""
    for field in ("business_url", "jump_url", "play_url"):
        url = str(raw.get(field) or "").strip()
        if not _is_zhihu_target(url):
            continue
        parsed = urlparse(url)
        # 不向前端传递查询参数，其中可能包含分享追踪或登录参数。
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        source = source or clean
        host = (parsed.hostname or "").lower()
        if ((host == "www.zhihu.com" and
             (_COLUMN.fullmatch(parsed.path) or _ANSWER.fullmatch(parsed.path))) or
                (host == "zhuanlan.zhihu.com" and _ARTICLE.fullmatch(parsed.path))):
            return AccountShelfBook(book_id, str(raw.get("title") or "未命名"), kind,
                                    url=clean, source_url=clean, supported=True)
    if kind.lower() == "live" or raw.get("product_type") == "live":
        reason = "Live 音视频暂不支持导出为电子书。"
    elif raw.get("producer") == "work" or kind == "short_story":
        reason = "新版短故事未提供可用的网页版正文链接，当前下载内核不支持。"
    elif source and urlparse(source).hostname == "story.zhihu.com":
        reason = "该条目仅提供 App 阅读链接，当前下载内核不支持。"
    else:
        reason = "该条目没有现有下载内核支持的网页版链接。"
    return AccountShelfBook(book_id, str(raw.get("title") or "未命名"), kind,
                            source_url=source, unsupported_reason=reason)


def fetch_account_shelf(client: ZhihuClient, offset: int = 0,
                        limit: int = 10) -> AccountShelfPage:
    if not client.get_cookies().get("z_c0"):
        raise AuthError("请先扫码登录知乎，再刷新账号书架。")
    # 登录失效不能被服务端的空列表伪装成空书架。
    me = _fetch_json(client, "https://www.zhihu.com/api/v4/me")
    if not me.get("id"):
        raise AuthError("知乎登录已失效，请重新扫码登录后刷新账号书架。")
    url = ACCOUNT_SHELF_URL if offset == 0 and limit == 10 else (
        f"{ACCOUNT_SHELF_URL}?limit={limit}&offset={offset}")
    data = _fetch_json(client, url)
    rows, pagination = data.get("data"), data.get("pagination")
    if (not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows)
            or not isinstance(pagination, dict)
            or not isinstance(pagination.get("is_end"), bool)):
        raise ParseError("账号书架数据结构发生变化，请更新程序后重试。")
    try:
        total = _integer(pagination["totals"])
        if _integer(pagination["offset"]) != offset:
            raise ValueError
        next_offset = None
        if not pagination["is_end"]:
            parsed = urlparse(str(pagination["next"]))
            if (parsed.scheme != "https" or parsed.netloc != "api.zhihu.com"
                    or parsed.path != "/pluton/shelves" or not rows):
                raise ValueError
            next_offset = _integer(parse_qs(parsed.query)["offset"][0])
            if next_offset <= offset:
                raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        raise ParseError("账号书架分页信息异常，已停止加载，避免重复或遗漏书目。") from exc
    seen: set[str] = set()
    books = []
    for row in rows:
        book = normalize_book(row)
        if book.id not in seen:
            seen.add(book.id)
            books.append(book)
    return AccountShelfPage(books, total, next_offset)
