"""Decode embedded Zhihu fonts using glyph names or rendered-glyph OCR.

Identity uniXXXX names describe encoded code points, not visible glyphs, so
these require OCR too. Each font family owns a separate character mapping;
translations apply only to text inheriting that family, never HTML source.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from functools import lru_cache
from unicodedata import normalize

from bs4 import BeautifulSoup, NavigableString

__all__ = ["deobfuscate", "build_translation"]

logger = logging.getLogger(__name__)

#: 匹配内联 @font-face 中 truetype/opentype 的 data URI（知乎盐选反爬字体）。
#: 兼容 url('...') 与 url(...)，允许 src 前先有 font-family（非贪婪跨到 src）。
_FONT_FACE_RE = re.compile(
    r"@font-face\s*\{[^{}]*?"
    r"src:\s*url\(\s*['\"]?"
    r"data:font/ttf;charset=utf-8;base64,([A-Za-z0-9+/=\s]+?)"
    r"['\"]?\s*\)",
    re.IGNORECASE | re.DOTALL,
)

#: uniXXXX（4 位）或 uniXXXXXX（6 位）两种已知字形名形态。
_UNI_NAME_RE = re.compile(r"^uni([0-9A-Fa-f]{4}|[0-9A-Fa-f]{6})$")

#: OCR 依赖缺失时只在首次提醒（避免每章都打一遍告警日志）。
_OCR_WARNED = False


def _extract_fonts(html: str) -> list[bytes]:
    """从 HTML 中抽取所有内联 ttf/otf @font-face，解码为字节列表。"""
    fonts: list[bytes] = []
    for match in _FONT_FACE_RE.finditer(html):
        b64 = re.sub(r"\s+", "", match.group(1))
        try:
            data = base64.b64decode(b64, validate=True)
        except Exception:  # 非法 base64 → 跳过该字体
            continue
        if data:
            fonts.append(data)
    return fonts


def _glyphname_map(font_bytes: bytes) -> dict[str, str]:
    """字形名路径：cmap 条形名 uniXXXX → 真实字符。非 uniXXXX 形态返回空。"""
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(io.BytesIO(font_bytes))
        try:
            cmap = font.getBestCmap() or {}
        finally:
            font.close()
    except Exception:
        return {}

    mapping: dict[str, str] = {}
    for src_code, glyph in cmap.items():
        if not isinstance(glyph, str):
            continue
        uni = _UNI_NAME_RE.match(glyph)
        if uni is None:
            continue
        try:
            true = normalize("NFKC", chr(int(uni.group(1), 16)))
        except (ValueError, OverflowError):
            continue
        if len(true) == 1 and ord(true) > 32 and true != chr(src_code):
            mapping[chr(src_code)] = true
    return mapping


def _log_ocr_unavailable() -> None:
    """OCR 依赖缺失时打一次性告警（避免每章刷屏）。"""
    global _OCR_WARNED
    if _OCR_WARNED:
        return
    _OCR_WARNED = True
    logger.warning(
        "未检测到 OCR 解码依赖（Pillow / ddddocr）：若知乎字体已被随机化字形名，"
        "正文乱码将无法还原。可用 `pip install Pillow ddddocr` 开启完整解码。"
    )


@lru_cache(maxsize=32)
def _ocr_map(font_bytes: bytes) -> dict[str, str]:
    """OCR 路径：字形名随机化时，逐字形渲染 + ddddocr 还原真实字符。"""
    try:
        import ddddocr
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        _log_ocr_unavailable()
        return {}

    try:
        from fontTools.ttLib import TTFont

        font = TTFont(io.BytesIO(font_bytes))
        try:
            cmap = font.getBestCmap() or {}
        finally:
            font.close()
        pil_font = ImageFont.truetype(io.BytesIO(font_bytes), 89)
    except Exception:
        return {}

    try:
        engine = ddddocr.DdddOcr(show_ad=False)
    except Exception:
        return {}

    mapping: dict[str, str] = {}
    size = 128
    for code in cmap.keys():
        char = chr(code)
        if ord(char) <= 32:
            continue
        try:
            img = Image.new("RGB", (size, size), "white")
            draw = ImageDraw.Draw(img)
            draw.text(
                (size / 2, size / 2), char, fill="black", font=pil_font, anchor="mm"
            )
            text = (engine.classification(img) or "").strip()
            if len(text) == 1 and text != char:
                mapping[char] = text
        except Exception:  # 单字形渲染/识别失败：跳过，不整体失败
            continue
    return mapping


def build_translation(html: str) -> dict[str, str]:
    """对某页 HTML 构建「被替换字符 → 真实字符」的翻译字典。

    遍历内联字体：优先字形名 uniXXXX 解码；字形名随机化（结果为空）时回退
    OCR。跨字体取并集、先到先得；只保留确实出现在页面文本里的源字符，避免
    图标字体等的垃圾映射污染正文。

    Args:
        html: 章节页原始 HTML。

    Returns:
        翻译字典；无字体或无法解码时返回空字典。
    """
    if not html or "@font-face" not in html.lower():
        return {}
    present = set(html)
    merged: dict[str, str] = {}
    for font_bytes in _extract_fonts(html):
        mapping = _glyphname_map(font_bytes) or _ocr_map(font_bytes)
        for src, true in mapping.items():
            if src in present:
                merged.setdefault(src, true)
    return merged


def deobfuscate(html: str) -> str:
    """Decode text using its inherited font family; preserve scripts and attributes.

    Inline styles override simple stylesheet selectors. Pages without any
    matching selectors retain the legacy text/meta fallback.
    """
    if not html or "@font-face" not in html.lower():
        return html
    soup = BeautifulSoup(html, "html.parser")
    families: dict[str, dict[str, str]] = {}
    for face in re.finditer(r"@font-face\s*\{[^{}]*\}", html, re.I):
        family = re.search(r"font-family\s*:\s*([^;]+)", face.group(), re.I)
        if not family:
            continue
        name = family.group(1).strip().strip("\"'")
        if name in families:  # normal/bold variants have the same encoding
            continue
        fonts = _extract_fonts(face.group())
        if fonts:
            families[name] = _glyphname_map(fonts[0]) or _ocr_map(fonts[0])
    if not any(families.values()):
        return html

    assigned: dict[int, str] = {}
    def assign(node, declaration):
        match = re.search(r"font-family\s*:\s*([^;}{]+)", declaration, re.I)
        if match:
            name = match.group(1).split(",")[0].strip().strip("\"'")
            assigned[id(node)] = name

    # Simple CSS selectors plus inline style cover server-rendered chapter pages.
    for style in soup.find_all("style"):
        css = re.sub(r"@font-face\s*\{[^{}]*\}", "", style.get_text(), flags=re.I)
        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            if "font-family" not in rule.group(2).lower():
                continue
            try:
                for node in soup.select(rule.group(1).strip()):
                    assign(node, rule.group(2))
            except Exception:
                continue
    for node in soup.find_all(style=True):
        assign(node, node["style"])
    scoped = any(name in families for name in assigned.values())
    fallback = str.maketrans(build_translation(html)) if not scoped else {}
    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString) or node.parent.name in ("style", "script"):
            continue
        table = fallback
        if scoped:
            for parent in node.parents:
                if parent.has_attr("data-font-decoded"):
                    table = {}
                    break
                if id(parent) in assigned:
                    table = str.maketrans(families.get(assigned[id(parent)], {}))
                    break
        if table:
            node.replace_with(str(node).translate(table))
    for node in soup.find_all(True):
        if assigned.get(id(node)) in families:
            node["data-font-decoded"] = "true"
    if not scoped:  # Legacy pages without a font selector.
        for node in soup.find_all("meta", content=True):
            node["content"] = node["content"].translate(fallback)
    return str(soup)
