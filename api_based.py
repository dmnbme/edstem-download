import base64
import json
import mimetypes
import os
import re
import time
import html
from typing import Dict, List, Tuple, Any

import requests
import pypandoc  # 直接导入

ED_HOST = "https://edstem.org/api"


# ==========================
# 通用工具
# ==========================

def request(
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    **kwargs: Any,
) -> requests.Response:
    """
    简单封装 requests.request，带重试。
    - 对网络异常、5xx（包括 525）以及 429 进行最多 `retries` 次重试。
    - 仍失败则抛出异常。
    """
    last_exception: Exception | None = None

    for attempt in range(1, retries + 1):
        status = ""
        body_repr = ""

        try:
            resp = requests.request(method, url, **kwargs)
            status = str(resp.status_code)

            # 只在需要打印时才访问 text，避免二进制内容乱掉
            try:
                body_repr = repr(resp.text)
            except Exception:
                body_repr = "<non-text response>"

            # 成功
            if 200 <= resp.status_code <= 299:
                return resp

            # 429 / 5xx 暂时性问题，重试
            if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                if attempt < retries:
                    print(
                        f"Request got bad status {resp.status_code}, "
                        f"retrying ({attempt}/{retries})..."
                    )
                    time.sleep(backoff * attempt)
                    continue

            # 其他状态码不重试，直接抛异常
            raise Exception(f"Bad status code: {resp.status_code}")

        except Exception as e:
            last_exception = e
            print("Request failed")
            print(f"Status: {status}")
            print(f"URL: {url}")
            print(f"Body: {body_repr}")

            if attempt < retries:
                print(f"Retrying ({attempt}/{retries})...")
                time.sleep(backoff * attempt)
                continue
            else:
                # 最后一次仍失败，往外抛
                raise e

    # 理论上不会到这里
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected request() failure")


def choice_validate(options: List[str], message: str) -> int:
    """让用户在给定 options 里选一个数字（字符串形式），返回选中的 int 值。"""
    while True:
        user_choice = input(message).strip()
        if user_choice in options:
            return int(user_choice)
        else:
            print("Invalid input. Try again.")


def safe_filename(name: str) -> str:
    """
    把课程名 / module 名 / lesson 名变成安全一点的文件名：
    - 去掉首尾空格
    - 把非法路径字符替换成下划线
    - 把连续空白压成单个空格
    """
    if not name:
        return "unnamed"

    name = name.strip()
    # Windows 不允许的字符，Mac / Linux 用这个也安全
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name


def shift_markdown_headings(md: str, offset: int = 1) -> str:
    """
    把 Markdown 里的标题级别整体下移 offset 级。
    例如 offset=1:  # → ##, ## → ###, ...，最多到 ######。
    """

    def _repl(match: re.Match) -> str:
        hashes = match.group(1)
        text = match.group(2)
        new_level = min(len(hashes) + offset, 6)
        return "#" * new_level + " " + text

    return re.sub(r"^(#{1,6})\s+(.*)$", _repl, md, flags=re.MULTILINE)


# ==========================
# Ed 相关逻辑
# ==========================

def select_course(ed_url: str, token: str) -> dict:
    """
    调 /user 拿到 courses，按 code 排序并让用户选择一个。
    返回被选中的 course 对象（包含 course / role / lab 等字段）。
    """
    r = request(
        "GET",
        ed_url + "/user",
        headers={"Authorization": "Bearer " + token},
    )
    u = r.json()

    courses = sorted(u["courses"], key=lambda x: x["course"]["code"])
    no_list: List[str] = []

    print("\n=== Your courses on Ed ===")
    for idx, c in enumerate(courses, start=1):
        code = c["course"]["code"]
        name = c["course"]["name"]
        print(f"{idx}. {code} {name}")
        no_list.append(str(idx))

    choice = choice_validate(no_list, "\nSelect the course you want: ")
    selected_course = courses[choice - 1]
    print(
        f"\nYou selected: {selected_course['course']['code']} "
        f"{selected_course['course']['name']}\n"
    )
    return selected_course


def list_lessons_for_course(
    ed_url: str,
    token: str,
    course_id: int,
) -> Tuple[List[dict], Dict[int, str]]:
    """
    调 /courses/<course_id>/lessons，
    1. 返回按 lesson id 排序后的 lessons 列表
    2. 同时构造 module_id -> module_name 的映射（来自同一个响应里的 "modules" 字段）
    3. 如果 lessons 为空，打印提示并返回空。
    """
    lessons_url = f"{ed_url}/courses/{course_id}/lessons"
    r = request("GET", lessons_url, headers={"Authorization": "Bearer " + token})
    data = r.json()

    lessons = data.get("lessons", [])
    modules_list = data.get("modules", [])

    if not lessons:
        print("This course currently has no lessons (API returned an empty list).")
        return [], {}

    # ---- lesson 按 id 排序 ----
    lessons_sorted = sorted(
        lessons,
        key=lambda l: (l.get("id") is None, l.get("id") or 0),
    )

    print("=== Lessons in this course (sorted by lesson_id) ===")
    for idx, lesson in enumerate(lessons_sorted, start=1):
        lesson_id = lesson.get("id")
        title = lesson.get("title")
        ltype = lesson.get("type")  # general / python / go ...
        module_id = lesson.get("module_id")

        print(
            f"{idx:2d}. "
            f"[id={lesson_id}] "
            f"type={ltype:<8} "
            f"module={module_id:<6} "
            f"- {title}"
        )
    print()

    # ---- lesson type 统计 ----
    type_counter: Dict[str, int] = {}
    for lesson in lessons_sorted:
        t = lesson.get("type") or "unknown"
        type_counter[t] = type_counter.get(t, 0) + 1

    print("Lesson type summary:")
    for t, count in sorted(type_counter.items(), key=lambda x: x[0]):
        print(f"  {t}: {count}")
    print()

    # ---- module_id -> module_name 映射（来自同一响应里的 modules）----
    module_name_map: Dict[int, str] = {}
    for m in modules_list:
        mid = m.get("id")
        if isinstance(mid, int):
            mname = m.get("name") or m.get("title") or f"module_{mid}"
            module_name_map[mid] = mname

    return lessons_sorted, module_name_map


def edxml_to_markdown(xml: str) -> str:
    """
    用 pypandoc 把 Ed 的 <document> XML 尽量转成 Markdown。
    - 先处理 <web-snippet>，把其中的 HTML/CSS/JS 抽出来，变成原始 HTML 片段，用占位符保护。
    - 再做一些 tag 替换，让它更接近 HTML，再交给 pandoc。
    """
    if not xml:
        return ""

    # ==========
    # 1. 先处理 web-snippet，抽出里面的 HTML/CSS/JS，做成 raw HTML 块
    #    用占位符防止 pandoc 把它变成表格 / 标题等。
    # ==========

    web_snippet_blocks: Dict[str, str] = {}

    def _web_snippet_repl(match: re.Match) -> str:
        full_block = match.group(0)

        # 找出所有 web-snippet-file
        files = re.findall(
            r'<web-snippet-file[^>]*language="([^"]+)"[^>]*>(.*?)</web-snippet-file>',
            full_block,
            flags=re.DOTALL,
        )

        html_code_parts: List[str] = []
        css_code_parts: List[str] = []
        js_code_parts: List[str] = []

        for lang, content in files:
            # content 里面有 &lt; 之类，要还原成真正的 HTML
            text = html.unescape(content)
            lang = (lang or "").lower()
            if lang == "html":
                html_code_parts.append(text.strip())
            elif lang == "css":
                css_code_parts.append(text.strip())
            elif lang == "js" or lang == "javascript":
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
            # 实在没东西，就干掉这个 web-snippet
            return ""

        placeholder = f"EDRAWHTMLBLOCK_{len(web_snippet_blocks)}"
        web_snippet_blocks[placeholder] = raw_html
        return placeholder

    xml_processed = re.sub(
        r"<web-snippet[^>]*>.*?</web-snippet>",
        _web_snippet_repl,
        xml,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # ==========
    # 2. 把 Ed XML 映射成 HTML-ish
    # ==========

    html_like = xml_processed

    # heading level -> h1/h2...
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

    # 去掉 document 根标签，替换 paragraph 为 p
    html_like = re.sub(r"</?document[^>]*>", "", html_like)
    html_like = (
        html_like.replace("<paragraph", "<p")
        .replace("</paragraph>", "</p>")
    )
    # 换行标记
    html_like = html_like.replace("<break>", "<br />").replace("</break>", "")

    # 图片转 base64 data URI
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
            mime = resp.headers.get("Content-Type") or mimetypes.guess_type(src)[0] or mime
            b64 = base64.b64encode(content).decode("ascii")
            data_uri = f"data:{mime};base64,{b64}"
        except Exception as e:
            print(f"Image download failed for {src}: {e}")

        w_attr = f' width="{width_match.group(1)}"' if width_match else ""
        h_attr = f' height="{height_match.group(1)}"' if height_match else ""
        return f'<img src="{data_uri}" alt=""{w_attr}{h_attr} />'

    html_like = re.sub(
        r"<image([^>]*)\/?>",
        _image_repl,
        html_like,
        flags=re.IGNORECASE,
    )

    # 列表 <list style="number"> / <list style="bullet">
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

    html_like = _convert_lists(html_like)
    html_like = (
        html_like.replace("<list-item", "<li")
        .replace("</list-item>", "</li>")
    )

    # 文本样式
    html_like = (
        html_like.replace("<bold>", "<strong>").replace("</bold>", "</strong>")
        .replace("<italic>", "<em>").replace("</italic>", "</em>")
        .replace("<underline>", "<u>").replace("</underline>", "</u>")
    )
    # <strong>xxx<br /></strong> → <strong>xxx</strong><br />
    html_like = re.sub(
        r"<(strong|em|u)>([^<]*?)<br\s*/>\s*</\1>",
        r"<\1>\2</\1><br />",
        html_like,
        flags=re.DOTALL,
    )

    # 代码片段 <snippet language="py"> <snippet-file>...</snippet-file> </snippet>
    def _snippet_repl(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2) or ""
        code_raw = html.unescape(code.strip("\n"))
        code_html = html.escape(code_raw)
        lang_class = lang.strip()
        class_attr = f' class="language-{lang_class}"' if lang_class else ""
        # 这里仍然用 <pre><code>，让 pandoc 识别为代码块
        return f"<pre><code{class_attr}>{code_html}</code></pre>"

    html_like = re.sub(
        r'<snippet[^>]*?language="([^"]*)"[^>]*>\s*'
        r'<snippet-file[^>]*?>(.*?)</snippet-file>\s*</snippet>',
        _snippet_repl,
        html_like,
        flags=re.DOTALL,
    )

    # 链接
    html_like = re.sub(
        r"<link\s+href=\"([^\"]+)\"\s*>",
        r'<a href="\1">',
        html_like,
    )
    html_like = html_like.replace("</link>", "</a>")

    # ==========
    # 3. 调用 pandoc 把 HTML-ish 转成 Markdown
    # ==========

    md = pypandoc.convert_text(
        html_like,
        "md",
        format="html",
        extra_args=["--wrap=none"],
    )

    # 将 markdown 图像语法转换为 HTML，去掉 {width=".."} 之类的扩展语法
    def _img_md_to_html(match: re.Match) -> str:
        alt = match.group(1) or ""
        src = match.group(2) or ""
        attrs = match.group(3) or ""
        width_match = re.search(r'width="([^"]+)"', attrs)
        height_match = re.search(r'height="([^"]+)"', attrs)
        w_attr = f' width="{width_match.group(1)}"' if width_match else ""
        h_attr = f' height="{height_match.group(1)}"' if height_match else ""
        return f'<img src="{src}" alt="{alt}"{w_attr}{h_attr}>'

    md = re.sub(
        r'!\[(.*?)\]\((.*?)\)(\{[^}]*\})?',
        _img_md_to_html,
        md,
        flags=re.DOTALL,
    )

    # 清理 pandoc 生成的一些小瑕疵
    cleaned_lines: List[str] = []
    in_code_block = False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            cleaned_lines.append(line.rstrip("\n"))
            in_code_block = not in_code_block
            continue
        if in_code_block:
            cleaned_lines.append(line.rstrip("\n"))
            continue

        if line.strip() == "<!-- -->":
            continue
        line = re.sub(r"^(\s*)(\d+)\.\s+-\s+", r"\1\2. ", line)
        line = re.sub(r"^(\s*)-\s+-\s+", r"\1- ", line)
        # 去掉粗体/斜体后紧跟的反斜杠（来自 HTML <br />）
        line = re.sub(r"(\\)(?=\*\*|__)", "", line)
        # 去掉行尾用于强制换行的反斜杠
        if line.rstrip().endswith("\\"):
            line = re.sub(r"\\\s*$", "", line)
        cleaned_lines.append(line)

    md = "\n".join(cleaned_lines).strip()

    # ==========
    # 4. 把 web-snippet 的占位符替换回原始 HTML/CSS/JS
    # ==========

    for placeholder, raw_html in web_snippet_blocks.items():
        md = md.replace(placeholder, raw_html)

    return md.strip()


def fetch_lesson_content(ed_url: str, token: str, lesson: dict) -> dict:
    """
    获取单个 lesson 的内容（slides）：
    - 调 /lessons/<lesson_id>?view=1 拿到 slides 列表
    - 再根据 slide.type:
        - document: 获取 content XML + 转成 Markdown
        - quiz: 获取 questions / responses / states
        - 其他类型：先只记录基本信息
    返回结构化的 dict。
    """
    lesson_id = lesson["id"]
    lesson_title = lesson.get("title")
    lesson_type = lesson.get("type")

    print(f"Fetching lesson {lesson_id} - {lesson_title!r} (type={lesson_type}) ...")

    lesson_url = f"{ed_url}/lessons/{lesson_id}?view=1"
    r = request(
        "GET",
        lesson_url,
        headers={"Authorization": "Bearer " + token},
    )
    data = r.json()
    lesson_detail = data.get("lesson", data)
    slides = lesson_detail.get("slides") or []

    processed_slides: List[dict] = []

    for s in slides:
        slide_id = s.get("id")
        if slide_id is None:
            continue

        slide_url = f"{ed_url}/lessons/slides/{slide_id}?view=1"
        rs = request(
            "GET",
            slide_url,
            headers={"Authorization": "Bearer " + token},
        )
        slide_json = rs.json()
        slide_data = slide_json.get("slide", slide_json)
        stype = slide_data.get("type")

        base_info = {
            "id": slide_id,
            "type": stype,
            "title": slide_data.get("title"),
            "index": slide_data.get("index"),
        }

        if stype == "document":
            content_xml = slide_data.get("content")
            content_md = edxml_to_markdown(content_xml)
            processed_slides.append(
                {
                    **base_info,
                    "content_xml": content_xml,
                    "content_md": content_md,
                }
            )

        elif stype == "quiz":
            q_base = f"{ed_url}/lessons/slides/{slide_id}/questions"

            rq = request(
                "GET",
                q_base,
                headers={"Authorization": "Bearer " + token},
            )
            rr = request(
                "GET",
                q_base + "/responses",
                headers={"Authorization": "Bearer " + token},
            )
            rs2 = request(
                "GET",
                q_base + "/states",
                headers={"Authorization": "Bearer " + token},
            )

            questions = rq.json().get("questions", rq.json())
            responses = rr.json().get("responses", rr.json())
            states = rs2.json().get("states", rs2.json())

            processed_slides.append(
                {
                    **base_info,
                    "passage": slide_data.get("passage"),
                    "questions": questions,
                    "responses": responses,
                    "states": states,
                }
            )
        else:
            # code / pdf / html 等等，先占坑
            processed_slides.append(base_info)

    result = {
        "lesson_meta": {
            "id": lesson_id,
            "title": lesson_title,
            "type": lesson_type,
        },
        "slides": processed_slides,
    }

    print(f"  -> fetched {len(processed_slides)} slides.")
    return result


def save_lesson_markdown(
    course_root: str,
    module_name_map: Dict[int, str],
    lesson: dict,
    lesson_struct: dict,
) -> None:
    """
    把一个 lesson 的所有 slides 写成一个 .md 文件：
    - 目录：<course_root>/<module_name>/<lesson_name>.md
    - 每个 slide 一个一级标题
    - slide 内部标题级别整体下移一层
    """
    module_id = lesson.get("module_id")
    if isinstance(module_id, int):
        module_name = module_name_map.get(module_id, f"module_{module_id}")
    else:
        module_name = "module_unknown"

    lesson_title = lesson.get("title") or f"lesson_{lesson['id']}"

    module_dir = os.path.join(course_root, safe_filename(module_name))
    os.makedirs(module_dir, exist_ok=True)

    file_path = os.path.join(
        module_dir,
        safe_filename(lesson_title) + ".md",
    )

    parts: List[str] = []

    for slide in lesson_struct.get("slides", []):
        stitle = slide.get("title") or f"Slide {slide.get('index')}"
        stype = slide.get("type")

        # 一级标题：slide 名
        parts.append(f"# {stitle}")

        if stype == "document":
            body = slide.get("content_md") or ""
            if body:
                body = shift_markdown_headings(body, offset=1)
                parts.append(body)
        elif stype == "quiz":
            parts.append("_Quiz slide: questions/responses not converted to markdown yet._")
        else:
            parts.append(f"_Slide of type `{stype}` not converted (code/pdf/etc)._")

    md_text = "\n\n".join(parts) + "\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"  -> saved markdown to {file_path}")


def export_course_lessons_to_markdown(ed_url: str, token: str) -> None:
    """
    主流程：
    1. 选择一个 course；
    2. 调 /courses/<course_id>/lessons，若无 lessons 则退出；
    3. 为该 course 下所有 lessons：
       - 获取 slides 内容；
       - 以 markdown 形式写入本地文件。
    """
    selected_course = select_course(ed_url, token)
    course_info = selected_course["course"]
    course_id = course_info["id"]
    course_code = course_info["code"]
    course_name = course_info["name"]

    course_dir_name = safe_filename(f"{course_code} {course_name}")
    course_root = os.path.join(os.getcwd(), course_dir_name)
    os.makedirs(course_root, exist_ok=True)

    lessons_sorted, module_name_map = list_lessons_for_course(ed_url, token, course_id)
    if not lessons_sorted:
        # 前面已经打印过提示，这里直接返回即可
        return

    total = len(lessons_sorted)
    for idx, lesson in enumerate(lessons_sorted, start=1):
        print(
            f"\n=== [{idx}/{total}] Processing lesson id={lesson['id']} "
            f"- {lesson.get('title')!r} ==="
        )
        lesson_struct = fetch_lesson_content(ed_url, token, lesson)
        save_lesson_markdown(course_root, module_name_map, lesson, lesson_struct)


def main() -> None:
    ed_url = ED_HOST
    # 建议从环境变量里读，不要把 PAT 写死在代码里
    token = os.environ.get("ED_PAT", "")
    token = "byVGl_.CG7HsNiPyPDGcxRbc5qX6nP2yIyQNjfGnDZ7ivNh"
    if not token:
        print("Please set your Ed PAT in the ED_PAT environment variable.")
        return

    export_course_lessons_to_markdown(ed_url, token)


if __name__ == "__main__":
    main()