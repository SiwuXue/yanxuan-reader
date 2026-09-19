"""parser 测试：结构保留（h2/h3/li/quote/img data-original）、标题降级链、
目录解析（含标题文本）、无标题/无正文报错、闸门页防线。全部离线（内联 HTML fixture）。"""

from __future__ import annotations

import pytest

from zhihu_downloader.errors import ParseError
from zhihu_downloader.parse.parser import (
    detect_gate_page,
    parse_article,
    parse_page_title,
    parse_toc,
)

SECTION_HTML = """
<html>
<head>
  <meta property="og:title" content="第十一章 雪夜来客" />
</head>
<body>
  <div class="Post-RichTextContainer">
    <div class="RichText">
      <h2>本章大标题</h2>
      <p>第一段正文。</p>
      <p>第二段<br>换行继续。</p>
      <h3>小节标题</h3>
      <ul><li>要点一</li><li>要点二</li></ul>
      <blockquote><p>引用中的段落。</p></blockquote>
      <figure><img src="data:image/gif;base64,placeholder" data-original="https://pic1.zhihu.com/real.png" alt="配图说明"></figure>
      <p><img src="https://pic2.zhihu.com/inline.png" alt=""></p>
      <script>var ad = "广告脚本内容";</script>
    </div>
  </div>
</body>
</html>
"""

COLUMN_HTML = """
<html>
<body>
  <a href="/market/paid_column/12345/section/6789">第一章 开篇</a>
  <a href="https://www.zhihu.com/market/paid_column/12345/section/6790">第二章 转折</a>
  <a href="/market/paid_column/12345/section/6789">重复章节</a>
  <a href="/market/paid_column/99999/section/1">别的专栏</a>
  <a href="/topic/hot">无关链接</a>
  <a href="/market/paid_column/12345/section/6791">   </a>
  <a href="/market/paid_column/12345/section/6792" title="属性标题"></a>
  <a href="/market/paid_column/12345/section/6793">番外 重逢</a>
</body>
</html>
"""

COLUMN_BASE = "https://www.zhihu.com/market/paid_column/12345"


class TestParseArticleStructure:
    """v5 关键升级：结构化 Block 列表。"""

    @pytest.fixture()
    def article(self):
        return parse_article(SECTION_HTML, "https://www.zhihu.com/market/paid_column/1/section/2")

    def test_title_and_url(self, article) -> None:
        assert article.title == "第十一章 雪夜来客"
        assert article.url == "https://www.zhihu.com/market/paid_column/1/section/2"

    def test_chapter_type_from_classifier(self, article) -> None:
        assert article.chapter_type == "normal"

    def test_block_kinds_in_document_order(self, article) -> None:
        assert [b.kind for b in article.blocks] == [
            "h2", "p", "p", "h3", "li", "li", "quote", "img", "img",
        ]

    def test_h2_h3_preserved(self, article) -> None:
        assert article.blocks[0].text == "本章大标题"
        assert article.blocks[3].text == "小节标题"

    def test_br_kept_as_newline(self, article) -> None:
        assert article.blocks[2].text == "第二段\n换行继续。"

    def test_li_items(self, article) -> None:
        assert [b.text for b in article.blocks if b.kind == "li"] == ["要点一", "要点二"]

    def test_quote_kept_and_nested_p_not_duplicated(self, article) -> None:
        quotes = [b for b in article.blocks if b.kind == "quote"]
        assert [q.text for q in quotes] == ["引用中的段落。"]
        occurrences = sum(1 for b in article.blocks if "引用中的段落" in b.text)
        assert occurrences == 1

    def test_img_prefers_data_original(self, article) -> None:
        img = article.blocks[7]
        assert img.src == "https://pic1.zhihu.com/real.png"
        assert img.alt == "配图说明"
        assert not img.src.startswith("data:")

    def test_img_plain_src_fallback(self, article) -> None:
        assert article.blocks[8].src == "https://pic2.zhihu.com/inline.png"

    def test_script_noise_dropped(self, article) -> None:
        assert all("广告脚本" not in b.text for b in article.blocks)

    def test_plain_text_flattening(self, article) -> None:
        text = article.plain_text()
        assert "第一段正文。" in text
        assert "本章大标题" in text
        assert "- 要点一" in text
        assert "> 引用中的段落。" in text


class TestTitleFallbackChain:
    """og:title > h1.Post-Title > h1 > title。"""

    def test_og_title_wins_over_h1(self) -> None:
        html = (
            "<html><head><meta property='og:title' content='OG标题'>"
            "<title>页面标题</title></head>"
            "<body><h1 class='Post-Title'>H1标题</h1><p>正文</p></body></html>"
        )
        assert parse_article(html).title == "OG标题"

    def test_post_title_wins_over_plain_h1(self) -> None:
        html = (
            "<html><head><title>页面标题</title></head><body>"
            "<h1>普通H1</h1><h1 class='Post-Title'>问题标题</h1><p>正文</p>"
            "</body></html>"
        )
        assert parse_article(html).title == "问题标题"

    def test_plain_h1_wins_over_title(self) -> None:
        html = "<html><head><title>页面标题</title></head><body><h1>H1标题</h1><p>正文</p></body></html>"
        assert parse_article(html).title == "H1标题"

    def test_title_tag_last(self) -> None:
        html = "<html><head><title>页面标题 </title></head><body><p>正文</p></body></html>"
        assert parse_article(html).title == "页面标题"

    def test_missing_title_raises(self) -> None:
        html = "<html><body><div class='RichText'><p>只有正文没有标题</p></div></body></html>"
        with pytest.raises(ParseError):
            parse_article(html)


class TestContentSelectorChain:
    """正文容器选择器降级链（同 v4）。"""

    @pytest.mark.parametrize(
        ("fragment", "expected"),
        [
            ('<div class="RichText"><p>甲内容</p></div>', "甲内容"),
            ('<div class="Post-RichTextContainer"><p>乙内容</p></div>', "乙内容"),
            ('<div class="RichContent-inner"><p>丙内容</p></div>', "丙内容"),
            ("<article><p>丁内容</p></article>", "丁内容"),
            ('<div class="Post-RichText"><p>戊内容</p></div>', "戊内容"),
        ],
    )
    def test_each_selector_works(self, fragment: str, expected: str) -> None:
        html = f"<html><head><title>T</title></head><body>{fragment}</body></html>"
        article = parse_article(html)
        assert article.blocks[0].text == expected

    def test_rich_text_preferred_over_outer_container(self) -> None:
        html = (
            "<html><head><title>T</title></head><body>"
            "<div class='Post-RichTextContainer'>"
            "<div class='RichText'><p>内层优先</p></div><p>外层忽略</p></div>"
            "</body></html>"
        )
        article = parse_article(html)
        assert [b.text for b in article.blocks] == ["内层优先"]

    def test_bare_text_container_falls_back_to_single_p(self) -> None:
        html = (
            "<html><head><title>T</title></head><body>"
            "<article>直接的文字内容，没有p标签。</article></body></html>"
        )
        article = parse_article(html)
        assert [b.kind for b in article.blocks] == ["p"]
        assert "直接的文字内容" in article.blocks[0].text

    def test_missing_content_raises(self) -> None:
        html = "<html><head><title>只有标题</title></head><body></body></html>"
        with pytest.raises(ParseError):
            parse_article(html)

    def test_error_messages_are_chinese_and_actionable(self) -> None:
        with pytest.raises(ParseError) as exc:
            parse_article("<html><body><p>无标题</p></body></html>")
        msg = str(exc.value)
        assert "Cookie" in msg or "登录" in msg  # 给出下一步操作建议


class TestParseToc:
    """parse_toc：链接 + 标题文本 + 序号 + 分类。"""

    @pytest.fixture()
    def refs(self):
        return parse_toc(COLUMN_HTML, COLUMN_BASE)

    def test_urls_absolute_dedup_same_column(self, refs) -> None:
        assert [r.url for r in refs] == [
            "https://www.zhihu.com/market/paid_column/12345/section/6789",
            "https://www.zhihu.com/market/paid_column/12345/section/6790",
            "https://www.zhihu.com/market/paid_column/12345/section/6791",
            "https://www.zhihu.com/market/paid_column/12345/section/6792",
            "https://www.zhihu.com/market/paid_column/12345/section/6793",
        ]

    def test_titles_extracted(self, refs) -> None:
        assert refs[0].title == "第一章 开篇"
        assert refs[1].title == "第二章 转折"

    def test_empty_link_text_falls_back_to_title_attr(self, refs) -> None:
        assert refs[2].title == ""  # 纯空白链接文本
        assert refs[3].title == "属性标题"

    def test_index_is_one_based_and_ordered(self, refs) -> None:
        assert [r.index for r in refs] == [1, 2, 3, 4, 5]

    def test_type_from_classifier(self, refs) -> None:
        assert refs[0].type == "normal"
        assert refs[4].type == "extra"

    def test_empty_when_no_sections(self) -> None:
        html = "<html><body><a href='/other'>无章节</a></body></html>"
        assert parse_toc(html, COLUMN_BASE) == []


class TestParsePageTitle:
    def test_returns_title(self) -> None:
        assert parse_page_title(SECTION_HTML) == "第十一章 雪夜来客"

    def test_returns_empty_when_missing(self) -> None:
        assert parse_page_title("<html><body><p>无标题</p></body></html>") == ""


# ----------------------------------------------------------------------
# 闸门页防线（登录态失效时知乎返回 HTTP 200 而非 403，client 层看不出来）
# ----------------------------------------------------------------------

#: 真实事故的脱敏复现：登录态失效时知乎返回的闸门页 —— HTTP 200、标题是
#: 站点默认值、页面上只有几张 logo 图，没有任何正文容器。
#: 旧实现把它存成「已完成章节」，导出成 4.5KB 的空白 epub，且续传永远跳过。
GATE_HTML = """
<html>
<head><title>知乎 - 有问题，就会有答案</title></head>
<body>
  <img src="https://static.zhihu.com/heifetz/assets/wechat-share-logo.png" alt="ZhiHu logo">
  <img src="https://pic2.zhimg.com/80/v2-f6b1f64a098b891b4ea1e3104b5b71f6_720w.png" alt="知乎 LOGO">
  <img src="https://pic3.zhimg.com/80/v2-d0289dc0a46fc5b15b3363ffa78cf6c7.png" alt="">
  <img src="https://pica.zhimg.com/80/v2-ccdb7828c12afff31a27e51593d23260_720w.png" alt="本站提供适老化无障碍服务">
</body>
</html>
"""

#: 人机验证页（标题是「安全验证 - 知乎」，页面内嵌脚本引用 /account/unhuman）
UNHUMAN_HTML = """
<html>
<head><title>安全验证 - 知乎</title></head>
<body>
  <img src="https://static.zhihu.com/heifetz/assets/wechat-share-logo.png" alt="ZhiHu logo">
  <script src="https://static.zhihu.com/zse-ck/v4/x.js" data-next="/account/unhuman"></script>
</body>
</html>
"""


class TestGatePageDefence:
    """只有图片、没有任何文字的页面必须报错，不能当成功。"""

    def test_gate_page_raises_instead_of_empty_article(self) -> None:
        with pytest.raises(ParseError) as exc:
            parse_article(GATE_HTML, "https://www.zhihu.com/market/paid_column/1/section/2")
        msg = str(exc.value)
        assert "登录" in msg and "验证" in msg
        assert "重新登录" in msg
        # 断点里的空壳会被自动排除，不应再叫用户手动清缓存（--no-resume）
        assert "自动识别并重新抓取" in msg
        assert "--no-resume" not in msg

    def test_unhuman_page_raises(self) -> None:
        with pytest.raises(ParseError) as exc:
            parse_article(UNHUMAN_HTML)
        assert "登录" in str(exc.value)

    def test_image_only_without_container_raises(self) -> None:
        """有 og:title、但既无正文容器也无文字 → 不是闸门页，按「只有图片」报。"""
        html = (
            "<html><head><meta property='og:title' content='某章节'>"
            "<title>某章节</title></head><body>"
            "<img src='https://pic.zhihu.com/a.png' alt='图'></body></html>"
        )
        with pytest.raises(ParseError) as exc:
            parse_article(html)
        assert "只有图片" in str(exc.value)

    def test_image_only_without_og_title_is_reported_as_gate_page(self) -> None:
        """无 og:title 又无容器 → 按闸门页报（提示重新登录），不让用户去猜链接。"""
        html = (
            "<html><head><title>某页面</title></head><body>"
            "<img src='https://pic.zhihu.com/a.png' alt='图'></body></html>"
        )
        with pytest.raises(ParseError) as exc:
            parse_article(html)
        assert "登录" in str(exc.value)

    def test_image_chapter_inside_rich_text_is_allowed(self) -> None:
        """真·图片类章节（有 div.RichText 与 og:title）不得误杀。"""
        html = (
            "<html><head><meta property='og:title' content='插图章'>"
            "<title>插图章 - 知乎</title></head><body>"
            "<div class='RichText'><img src='https://pic.zhihu.com/manga.png' alt='第一页'></div>"
            "</body></html>"
        )
        article = parse_article(html)
        assert [b.kind for b in article.blocks] == ["img"]
        assert article.title == "插图章"

    def test_normal_article_is_not_gate_page(self) -> None:
        assert detect_gate_page(SECTION_HTML) is False

    def test_detect_gate_page_by_url_marker(self) -> None:
        assert detect_gate_page(UNHUMAN_HTML) is True

    def test_detect_gate_page_by_site_default_title(self) -> None:
        html = "<html><head><title>知乎 - 有问题，就会有答案</title></head><body><p>甲</p></body></html>"
        assert detect_gate_page(html) is True

    def test_detect_gate_page_by_missing_og_title_and_container(self) -> None:
        html = "<html><head><title>随便什么</title></head><body><p>甲</p></body></html>"
        assert detect_gate_page(html) is True

    def test_detect_gate_page_accepts_precomputed_title(self) -> None:
        assert detect_gate_page("<html><body><p>甲</p></body></html>", "安全验证 - 知乎") is True


class TestArticleHasBodyText:
    """「正文有效」的唯一口径（parse 层与 checkpoint 层共用）。"""

    def test_text_blocks_count(self) -> None:
        assert parse_article(SECTION_HTML).has_body_text() is True

    def test_whitespace_only_blocks_do_not_count(self) -> None:
        article = parse_article(SECTION_HTML)
        for block in article.blocks:
            block.text = "   "
            block.kind = "p"
        assert article.has_body_text() is False

    def test_image_only_article_has_no_body_text(self) -> None:
        article = parse_article(SECTION_HTML)
        article.blocks = [b for b in article.blocks if b.kind == "img"]
        assert article.blocks  # 确实只剩图片
        assert article.has_body_text() is False
