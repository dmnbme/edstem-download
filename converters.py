import base64
import html
import mimetypes
import re
from typing import Any, Dict, List

import requests
import pypandoc


def shift_markdown_headings(md: str, offset: int = 1) -> str:
    """把 Markdown 里的标题级别整体下移 offset 级。"""

    def _repl(match: re.Match) -> str:
        hashes = match.group(1)
        text = match.group(2)
        new_level = min(len(hashes) + offset, 6)
        return "#" * new_level + " " + text

    return re.sub(r"^(#{1,6})\s+(.*)$", _repl, md, flags=re.MULTILINE)


def _image_repl(match: re.Match) -> str:
    attrs = match.group(1)
    src_match = re.search(r'src="([^"]+)"', attrs)
    width_match = re.search(r'width="([^"]+)"', attrs)
    height_match = re.search(r'height="([^"]+)"', attrs)
    if not src_match:
        return ""
    src = src_match.group(1)

    data_uri = src
    mime = "application/octet-stream"

    try:
        resp = requests.get(src, timeout=10)
        resp.raise_for_status()
        content = resp.content
        mime = (
            resp.headers.get("Content-Type")
            or mimetypes.guess_type(src)[0]
            or mime
        )
        b64 = base64.b64encode(content).decode("ascii")
        data_uri = f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"Image download failed for {src}: {e}")

    w_attr = f' width="{width_match.group(1)}"' if width_match else ""
    h_attr = f' height="{height_match.group(1)}"' if height_match else ""
    return f'<img src="{data_uri}" alt=""{w_attr}{h_attr} />'


def _convert_lists(text: str) -> str:
    tokens = re.finditer(r"</?list(?!-item)[^>]*>", text)
    out_parts: List[str] = []
    stack: List[str] = []
    last_idx = 0

    for m in tokens:
        out_parts.append(text[last_idx: m.start()])
        tag = m.group(0)
        if tag.startswith("</"):
            list_type = stack.pop() if stack else "ul"
            out_parts.append(f"</{list_type}>")
        else:
            style_match = re.search(r'style="([^"]+)"', tag)
            style_val = style_match.group(1).lower() if style_match else ""
            list_type = "ol" if style_val == "number" else "ul"
            stack.append(list_type)
            out_parts.append(f"<{list_type}>")
        last_idx = m.end()

    out_parts.append(text[last_idx:])
    while stack:
        out_parts.append(f"</{stack.pop()}>")
    return "".join(out_parts)


def edxml_to_markdown(xml: str) -> str:
    """
    Ed <document> XML → Markdown（带 web-snippet / spoiler / 下划线 / Typora [ 修复）。
    依赖外部的:
      - _image_repl
      - _convert_lists
    """
    if not xml:
        return ""

    # ==========
    # 1. web-snippet 使用占位符保护
    # ==========
    web_snippet_blocks: Dict[str, str] = {}

    def _web_snippet_repl(match: re.Match) -> str:
        full_block = match.group(0)

        files = re.findall(
            r'<web-snippet-file[^>]*language="([^"]+)"[^>]*>(.*?)</web-snippet-file>',
            full_block,
            flags=re.DOTALL,
        )

        html_code_parts: List[str] = []
        css_code_parts: List[str] = []
        js_code_parts: List[str] = []

        for lang, content in files:
            text = html.unescape(content).strip()
            lang = (lang or "").lower()
            if lang == "html":
                html_code_parts.append(text.strip())
            elif lang == "css":
                css_code_parts.append(text.strip())
            elif lang in ("js", "javascript"):
                js_code_parts.append(text.strip())

        raw_html = ""
        if html_code_parts:
            raw_html += "\n".join(html_code_parts)
        if css_code_parts:
            css_block = "\n".join(css_code_parts)
            raw_html += f"\n<style>\n{css_block}\n</style>"
        if js_code_parts:
            js_block = "\n".join(js_code_parts)
            raw_html += f"\n<script>\n{js_block}\n</script>"

        if not raw_html:
            return ""

        raw_html = raw_html.strip()
        lower_html = raw_html.lower()

        # 如果 snippet 里本来就有 <iframe>，不要再套一层
        if "<iframe" in lower_html:
            final_block = f"\n\n{raw_html}\n\n"
        else:
            # 用 iframe srcdoc 包裹，隔离样式和 JS
            srcdoc_content = raw_html.replace("'", "&#39;").replace("\n", " ")
            srcdoc_content = re.sub(r"\s{2,}", " ", srcdoc_content)
            final_block = (
                "\n\n"
                f"<iframe srcdoc='{srcdoc_content}' "
                'style="width: 100%; height: 450px; border: none;"></iframe>'
                "\n\n"
            )

        placeholder = f"EDRAWHTMLBLOCK_{len(web_snippet_blocks)}"
        web_snippet_blocks[placeholder] = final_block
        return placeholder

    xml_processed = re.sub(
        r"<web-snippet[^>]*>.*?</web-snippet>",
        _web_snippet_repl,
        xml,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # ==========
    # 2. XML → HTML-ish
    # ==========

    html_like = xml_processed

    # heading level → <h1> / <h2>...
    def _heading_block(match: re.Match) -> str:
        level = int(match.group(1))
        level = min(max(level, 1), 6)
        content = match.group(2)
        return f"<h{level}>{content}</h{level}>"

    html_like = re.sub(
        r"<heading\s+level=\"(\d+)\"[^>]*>(.*?)</heading>",
        _heading_block,
        html_like,
        flags=re.DOTALL,
    )

    # 根标签 / 段落 / 换行
    html_like = re.sub(r"</?document[^>]*>", "", html_like)
    html_like = (
        html_like.replace("<paragraph", "<p")
        .replace("</paragraph>", "</p>")
    )
    html_like = html_like.replace("<break>", "<br />").replace("</break>", "")

    # 图片 <image> → <img src="data:...">
    html_like = re.sub(
        r"<image([^>]*)\/?>",
        _image_repl,
        html_like,
        flags=re.IGNORECASE,
    )

    # 列表 <list> / <list-item>
    html_like = _convert_lists(html_like)
    html_like = (
        html_like.replace("<list-item", "<li")
        .replace("</list-item>", "</li>")
    )

    # 文本样式：粗体 / 斜体 / 下划线
    html_like = (
        html_like.replace("<bold>", "<strong>").replace("</bold>", "</strong>")
        .replace("<italic>", "<em>").replace("</italic>", "</em>")
        .replace("<underline>", "<u>").replace("</underline>", "</u>")
    )
    html_like = re.sub(
        r"<(strong|em|u)>([^<]*?)<br\s*/>\s*</\1>",
        r"<\1>\2</\1><br />",
        html_like,
        flags=re.DOTALL,
    )

    # 代码片段 <snippet>
    def _snippet_repl(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2) or ""
        code_raw = html.unescape(code.strip("\n"))
        code_html = html.escape(code_raw)
        lang_class = lang.strip()
        class_attr = f' class="language-{lang_class}"' if lang_class else ""
        return f"<pre><code{class_attr}>{code_html}</code></pre>"

    html_like = re.sub(
        r'<snippet[^>]*?language="([^"]*)"[^>]*>\s*'
        r'<snippet-file[^>]*?>(.*?)</snippet-file>\s*</snippet>',
        _snippet_repl,
        html_like,
        flags=re.DOTALL,
    )

    # 链接 <link href="..."> → <a href="...">
    html_like = re.sub(
        r"<link\s+href=\"([^\"]+)\"\s*>",
        r'<a href="\1">',
        html_like,
    )
    html_like = html_like.replace("</link>", "</a>")

    # spoiler 用占位符保护
    spoiler_blocks: Dict[str, str] = {}

    def _spoiler_repl(match: re.Match) -> str:
        inner = match.group(1).strip()
        placeholder = f"EDSPOILERBLOCK_{len(spoiler_blocks)}"
        spoiler_html = f"\n\n<details><summary>Expand</summary>\n{inner}\n</details>\n\n"
        spoiler_blocks[placeholder] = spoiler_html
        return placeholder

    html_like = re.sub(
        r"<spoiler>(.*?)</spoiler>",
        _spoiler_repl,
        html_like,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # ==========
    # 3. pandoc: HTML → Markdown
    # ==========

    md = pypandoc.convert_text(
        html_like,
        "md",
        format="html",
        extra_args=["--wrap=none"],
    )

    # markdown 图片语法 → <img>
    def _img_md_to_html(match: re.Match) -> str:
        alt = match.group(1) or ""
        src = match.group(2) or ""
        attrs = match.group(3) or ""
        width_match = re.search(r'width="([^"]+)"', attrs or "")
        height_match = re.search(r'height="([^"]+)"', attrs or "")
        w_attr = f' width="{width_match.group(1)}"' if width_match else ""
        h_attr = f' height="{height_match.group(1)}"' if height_match else ""
        return f'<img src="{src}" alt="{alt}"{w_attr}{h_attr}>'

    md = re.sub(
        r'!\[(.*?)\]\((.*?)\)(\{[^}]*\})?',
        _img_md_to_html,
        md,
        flags=re.DOTALL,
    )

    # pandoc 产生的 [text]{.underline} → <u>text</u>
    md = re.sub(
        r"\[([^\]]+)\]\s*\{\.underline\}",
        r"<u>\1</u>",
        md,
    )

    # ==========
    # 3.5 Typora 数学模式 \[ / \] 修复 + “松散”尖括号处理
    #   - 删除会触发公式的 \[ / \]（代码块内不处理）
    #   - 对非 HTML 标签的 <...> 前加反斜杠，避免被当成标签
    # ==========

    # def _escape_loose_angles(line: str) -> str:
    #     # 匹配非 HTML 标签形式的 <...>
    #     pattern = r"<(?!/?[A-Za-z][A-Za-z0-9\-]*(?:\s[^>]*)?>)([^>]*)>"
    #     def repl(m: re.Match) -> str:
    #         inner = m.group(1)
    #         return f"\\<{inner}>"
    #     return re.sub(pattern, repl, line)

    cleaned_lines: List[str] = []
    in_code_block = False

    for line in md.splitlines():
        stripped = line.strip()

        # 代码块 fence
        if stripped.startswith("```"):
            cleaned_lines.append(line.rstrip("\n"))
            in_code_block = not in_code_block
            continue

        if in_code_block:
            # 代码块内部完全不动
            cleaned_lines.append(line.rstrip("\n"))
            continue

        # 非代码块行的清理
        if stripped == "<!-- -->":
            continue

        # 列表小修
        line = re.sub(r"^(\s*)(\d+)\.\s+-\s+", r"\1\2. ", line)
        line = re.sub(r"^(\s*)-\s+-\s+", r"\1- ", line)

        # 去掉粗体/斜体前多余反斜杠
        line = re.sub(r"(\\)(?=\*\*|__)", "", line)
        # 去掉用于强制换行的结尾反斜杠
        if line.rstrip().endswith("\\"):
            line = re.sub(r"\\\s*$", "", line)

        # Typora 数学触发符号：\[…\]
        # 这里只去掉反斜杠，不改方括号本身
        line = re.sub(r"\\(?=\[)", "", line)
        line = re.sub(r"\\(?=\])", "", line)

        # 处理“松散”的 <...>（非 HTML 标签）
        # line = _escape_loose_angles(line)

        cleaned_lines.append(line.rstrip("\n"))

    md = "\n".join(cleaned_lines).strip()

    # ==========
    # 4. 替换占位符（web-snippet / spoiler）
    # ==========

    for placeholder, block_html in web_snippet_blocks.items():
        md = md.replace(placeholder, block_html)

    for placeholder, spoiler_html in spoiler_blocks.items():
        md = md.replace(placeholder, spoiler_html)

    return md.strip()