"""fontdecode 测试：字形名 uniXXXX 路径、OCR 回退路径、无字体原样返回。

字形名路径离线构造一个迷你 TTF（cmap 条形名 uniXXXX），不需要真实字体文件。
OCR 回退通过 monkeypatch 假 _ocr_map 覆盖，避免依赖 ddddocr 本体。
"""

from __future__ import annotations

import base64
import io

from zhihu_downloader.parse.fontdecode import (
    build_translation,
    deobfuscate,
)


def _build_mini_ttf(char_map: dict[int, str], glyph_names: list[str]) -> bytes:
    """构造一个只含 cmap 的迷你 TTF：unicode → glyph 名。

    Args:
        char_map: {src_unicode: glyph_name}，即被替换字符 unicode → 字形名。
        glyph_names: 需出现在 glyphOrder 里的字形名（含 .notdef）。
    """
    from fontTools.fontBuilder import FontBuilder
    from fontTools.ttLib.tables._g_l_y_f import Glyph as GLYFGlyph

    fb = FontBuilder(1000, isTTF=True)
    glyph_order = [".notdef"] + list(dict.fromkeys(glyph_names))
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(char_map)
    empty = GLYFGlyph()
    fb.setupGlyf({name: empty for name in glyph_order})
    fb.setupHorizontalMetrics({name: (0, 0) for name in glyph_order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable(
        {
            "familyName": "xtest",
            "styleName": "Regular",
            "uniqueFontIdentifier": "xtest",
            "fullName": "xtest",
            "psName": "xtest",
        }
    )
    fb.setupOS2(
        sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200
    )
    fb.setupPost()
    fb.setupHead()
    out = io.BytesIO()
    fb.font.save(out)
    return out.getvalue()


def _html_with_font(font_bytes: bytes, body_text: str) -> str:
    """把字体字节内联进 <style>@font-face 的 data URI，并给出正文文本。"""
    b64 = base64.b64encode(font_bytes).decode()
    return (
        "<html><head><style>@font-face{font-family:x;"
        f"src:url(data:font/ttf;charset=utf-8;base64,{b64})}}</style></head>"
        f"<body><div class=\"RichText\"><p>{body_text}</p></div></body></html>"
    )


class TestGlyphNamePath:
    """知乎旧格式：字形名为 uniXXXX，直接可解码，无需 OCR。"""

    def test_glyphname_map_decodes(self) -> None:
        # 源字符 时(0x65F6)/这(0x8FD9) → 字形名 uni662F(是)/uni7684(的)
        font = _build_mini_ttf(
            {0x65F6: "uni662F", 0x8FD9: "uni7684"}, ["uni662F", "uni7684"]
        )
        html = _html_with_font(font, "时这室友进能擦边女。")
        out = deobfuscate(html)
        assert "是的室友进能擦边女。" in out
        assert "时" not in out
        assert "这" not in out

    def test_replaces_title_meta_too(self) -> None:
        # deobfuscate 在整页 HTML 级别生效，og:title 里的乱码也应被还原。
        font = _build_mini_ttf({0x65F6: "uni662F"}, ["uni662F"])
        b64 = base64.b64encode(font).decode()
        html = (
            "<html><head>"
            f"<style>@font-face{{font-family:x;src:url(data:font/ttf;charset=utf-8;base64,{b64})}}</style>"
            '<meta property="og:title" content="时章 风雪" />'
            "</head><body><div class=\"RichText\"><p>正文</p></div></body></html>"
        )
        assert "是章 风雪" in deobfuscate(html)


class TestOcrFallback:
    """字形名被随机化（非 uniXXXX）时回退 OCR；测试用假 OCR 覆盖。"""

    def test_ocr_used_when_glyphnames_randomized(self, monkeypatch) -> None:
        font = _build_mini_ttf({0x586B: "glyph94001"}, ["glyph94001"])
        html = _html_with_font(font, "填性使然。")  # 0x586B 即 填
        monkeypatch.setattr(
            "zhihu_downloader.parse.fontdecode._ocr_map", lambda fb: {"填": "天"}
        )
        assert "天性使然。" in deobfuscate(html)


class TestEdgeCases:
    def test_no_font_returns_unchanged(self) -> None:
        html = '<div class="RichText"><p>普通正文，无字体反爬。</p></div>'
        assert deobfuscate(html) == html

    def test_empty_and_short_input(self) -> None:
        assert deobfuscate("") == ""
        assert deobfuscate("<html></html>") == "<html></html>"

    def test_glyphname_and_ocr_merge(self, monkeypatch) -> None:
        # 两个字体：一个可字形名解码，一个需 OCR；结果应并集、先到先得。
        f_glyph = _build_mini_ttf({0x65F6: "uni662F"}, ["uni662F"])
        f_ocr = _build_mini_ttf({0x586B: "glyph11"}, ["glyph11"])
        b64 = base64.b64encode(f_glyph).decode()
        b64b = base64.b64encode(f_ocr).decode()
        html = (
            "<style>@font-face{font-family:a;src:url(data:font/ttf;charset=utf-8;base64,"
            f"{b64})}}@font-face{{font-family:b;src:url(data:font/ttf;charset=utf-8;base64,"
            f"{b64b})}}</style><p>时我填谁</p>"
        )
        monkeypatch.setattr(
            "zhihu_downloader.parse.fontdecode._ocr_map", lambda fb: {"填": "天"}
        )
        assert build_translation(html) == {"时": "是", "填": "天"}
        out = deobfuscate(html)
        assert "是我天谁" in out


def test_identity_glyph_names_require_ocr(monkeypatch):
    font = _build_mini_ttf({ord("我"): "uni6211"}, ["uni6211"])
    monkeypatch.setattr(
        "zhihu_downloader.parse.fontdecode._ocr_map", lambda fb: {"我": "每"}
    )
    assert "每的故事" in deobfuscate(_html_with_font(font, "我的故事"))


def test_families_are_scoped_and_do_not_corrupt_source(monkeypatch):
    f1 = _build_mini_ttf({ord("会"): "uni4F1A"}, ["uni4F1A"])
    f2 = _build_mini_ttf({ord("会"): "uni4F1A", ord("每"): "uni6BCF"},
                         ["uni4F1A", "uni6BCF"])
    monkeypatch.setattr("zhihu_downloader.parse.fontdecode._ocr_map",
                        lambda fb: {"会": "在"} if fb == f1 else {"会": "不", "每": "我"})
    def face(name, font):
        return (f"@font-face{{font-family:{name};src:url(data:font/ttf;charset=utf-8;base64,"
                + base64.b64encode(font).decode() + ")}")
    html = ('<style>' + face('title', f1) + face('body', f2)
            + '.story{font-family:body}</style><h1>会每</h1>'
            + '<div class="story"><p data-value="会每">&#27599;弟，会下葬。</p>'
            + '<span style="font-family:title">会</span>'
            + '<span style="font-family:Arial">会每</span></div>'
            + '<script>const x="会每";</script>')
    from bs4 import BeautifulSoup
    out = deobfuscate(html)
    soup = BeautifulSoup(out, "html.parser")
    assert soup.p.text == "我弟，不下葬。"
    assert soup.p['data-value'] == "会每"
    assert soup.h1.text == "会每"
    assert [n.text for n in soup.find_all('span')] == ["在", "会每"]
    assert soup.script.string == 'const x="会每";'
    assert deobfuscate(out) == out
