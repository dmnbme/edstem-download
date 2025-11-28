import base64
import html
import json
import mimetypes
import re
from typing import List

import pypandoc
import requests

from .ast_parser import Node


def _download_image_as_data_uri(src: str) -> str:
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

    return data_uri


def _render_children(children: List[Node]) -> str:
    return "".join(_render_node(child) for child in children)


def _render_web_snippet(node: Node) -> str:
    html_code_parts: List[str] = []
    css_code_parts: List[str] = []
    js_code_parts: List[str] = []

    for child in node.children:
        if child.kind != "element" or child.tag != "web-snippet-file":
            continue
        lang = (child.attrs.get("language") or "").lower()
        content = ""
        if child.children:
            content = "".join(
                c.text for c in child.children if c.kind == "text"
            ).strip()
        content = html.unescape(content)

        if lang == "html":
            html_code_parts.append(content)
        elif lang == "css":
            css_code_parts.append(content)
        elif lang in ("js", "javascript"):
            js_code_parts.append(content)

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

    if "<iframe" in lower_html:
        return f"\n\n{raw_html}\n\n"

    srcdoc_content = raw_html.replace("'", "&#39;").replace("\n", " ")
    srcdoc_content = re.sub(r"\s{2,}", " ", srcdoc_content).strip()
    return (
        "\n\n"
        f"<iframe srcdoc='{srcdoc_content}' "
        'style="width: 100%; height: 450px; border: none;"></iframe>'
        "\n\n"
    )


def _render_node(node: Node) -> str:
    if node.kind == "text":
        return html.escape(node.text)

    tag = node.tag or ""
    if tag == "document":
        return _render_children(node.children)

    if tag == "paragraph":
        return f"<p>{_render_children(node.children)}</p>"

    if tag == "heading":
        level = node.attrs.get("level", "1")
        try:
            lvl_int = max(1, min(6, int(level)))
        except ValueError:
            lvl_int = 1
        return f"<h{lvl_int}>{_render_children(node.children)}</h{lvl_int}>"

    if tag == "break":
        return "<br />"

    if tag == "image":
        src = node.attrs.get("src") or ""
        if not src:
            return ""
        width = node.attrs.get("width")
        height = node.attrs.get("height")
        data_uri = _download_image_as_data_uri(src)

        attrs = [f'src="{data_uri}"', 'alt=""']
        if width:
            attrs.append(f'width="{width}"')
        if height:
            attrs.append(f'height="{height}"')
        return "<img " + " ".join(attrs) + " />"

    if tag == "list":
        style_val = (node.attrs.get("style") or "").lower()
        list_tag = "ol" if style_val == "number" else "ul"
        return f"<{list_tag}>{_render_children(node.children)}</{list_tag}>"

    if tag == "list-item":
        return f"<li>{_render_children(node.children)}</li>"

    if tag == "bold":
        return f"<strong>{_render_children(node.children)}</strong>"

    if tag == "italic":
        return f"<em>{_render_children(node.children)}</em>"

    if tag == "underline":
        return f"<u>{_render_children(node.children)}</u>"

    if tag == "link":
        href = node.attrs.get("href") or ""
        safe_href = html.escape(href, quote=True)
        return f'<a href="{safe_href}">{_render_children(node.children)}</a>'

    if tag == "snippet":
        lang = (node.attrs.get("language") or "").strip()
        code_parts: List[str] = []
        for child in node.children:
            if child.kind == "element" and child.tag == "snippet-file":
                code_parts.append(
                    "".join(c.text for c in child.children if c.kind == "text")
                )
        code_raw = "\n".join(code_parts).strip("\n")
        code_html = html.escape(html.unescape(code_raw))
        class_attr = f' class="language-{lang}"' if lang else ""
        return f"<pre><code{class_attr}>{code_html}</code></pre>"

    if tag == "web-snippet":
        return _render_web_snippet(node)

    if tag == "spoiler":
        inner = _render_children(node.children).strip()
        return (
            "\n\n"
            "<details><summary>Expand</summary>\n"
            f"{inner}\n"
            "</details>\n\n"
        )

    return _render_children(node.children)


def ast_to_html(node: Node) -> str:
    return _render_node(node)


def _html_to_markdown_via_ast(html_text: str) -> str:
    ast_json = pypandoc.convert_text(
        html_text,
        "json",
        format="html",
        extra_args=["--wrap=none"],
    )
    ast = json.loads(ast_json)

    md = pypandoc.convert_text(
        json.dumps(ast),
        "md",
        format="json",
        extra_args=["--wrap=none"],
    )
    return md.strip()

def _post_process_markdown(md: str) -> str:
    """
    Post-process the Markdown produced by pandoc to:
      - Convert image with size attributes to <img> tags
      - Convert pandoc underline spans to <u>...</u>
      - Fix duplicated list markers
      - Clean up stray backslashes
      - Remove Typora math trigger backslashes around [ and ]
    """
    md = md or ""
    if not md.strip():
        return md.strip()

    # Markdown image syntax with {width=".."} etc. -> <img ...>
    def _img_md_to_html(match: re.Match) -> str:
        alt = match.group(1) or ""
        src = match.group(2) or ""
        attrs = match.group(3) or ""

        width_match = re.search(r'width="([^"]+)"', attrs or "")
        height_match = re.search(r'height="([^"]+)"', attrs or "")

        w_attr = f' width="{width_match.group(1)}"' if width_match else ""
        h_attr = f' height="{height_match.group(1)}"' if height_match else ""

        # always emit a plain <img> tag
        return f'<img src="{src}" alt="{alt}"{w_attr}{h_attr}>'

    md = re.sub(
        r'!\[(.*?)\]\((.*?)\)(\{[^}]*\})?',
        _img_md_to_html,
        md,
        flags=re.DOTALL,
    )

    # pandoc underline span: [text]{.underline} -> <u>text</u>
    md = re.sub(
        r"\[([^\]]+)\]\s*\{\.underline\}",
        r"<u>\1</u>",
        md,
    )

    # Line-by-line cleanup ---
    cleaned_lines: List[str] = []
    in_code_block = False

    for line in md.splitlines():
        stripped = line.strip()

        # Code block fence: do not touch content inside fenced code blocks
        if stripped.startswith("```"):
            cleaned_lines.append(line.rstrip("\n"))
            in_code_block = not in_code_block
            continue

        if in_code_block:
            cleaned_lines.append(line.rstrip("\n"))
            continue

        # Remove empty HTML comment placeholders
        if stripped == "<!-- -->":
            continue

        # Fix pandoc list oddities: "1. - Item" and "- - Item"
        line = re.sub(r"^(\s*)(\d+)\.\s+-\s+", r"\1\2. ", line)
        line = re.sub(r"^(\s*)-\s+-\s+", r"\1- ", line)

        # Remove extra backslashes before bold/italic markers
        # e.g. \**bold** -> **bold**, \__italic__ -> __italic__
        line = re.sub(r"(\\)(?=\*\*|__)", "", line)

        # Remove trailing backslashes used for forced line breaks
        if line.rstrip().endswith("\\"):
            line = re.sub(r"\\\s*$", "", line)

        # math trigger
        # Here we only remove the backslash and keep the brackets unchanged
        line = re.sub(r"\\(?=\[)", "", line)
        line = re.sub(r"\\(?=\])", "", line)

        cleaned_lines.append(line.rstrip("\n"))

    return "\n".join(cleaned_lines).strip()

def ast_to_markdown(node: Node) -> str:
    html_text = ast_to_html(node)
    if not html_text.strip():
        return ""
    md = _html_to_markdown_via_ast(html_text)
    md = _post_process_markdown(md)
    return md
