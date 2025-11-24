import requests
import json
import os
import re
import time
import pypandoc

ED_HOST = "https://edstem.org/api"


def request(method, url, retries: int = 3, **kwargs):
    """简单封装一下 requests.request，统一报错信息 + 简单重试机制。"""
    last_exc = None

    for attempt in range(1, retries + 1):
        status = ""
        body = ""

        try:
            r = requests.request(method, url, **kwargs)
            status = r.status_code
            # 注意：PDF 等二进制就不要去访问 r.text 了，这里只在出错时打印
            body = r.text

            if 200 <= r.status_code <= 299:
                return r
            else:
                # 5xx（包括 525 这类 Cloudflare 错误）可以尝试重试
                if 500 <= r.status_code <= 599 and attempt < retries:
                    print(
                        f"Request got bad status {status}, retrying "
                        f"({attempt}/{retries}) ..."
                    )
                    time.sleep(attempt)  # 简单线性退避
                    continue

                # 其它情况直接抛错
                raise Exception(f"Bad status code: {status}")

        except Exception as e:
            last_exc = e
            # 网络错误 / 解析错误等也重试几次
            if attempt < retries:
                print(
                    f"Request error on attempt {attempt}/{retries}: {e}. "
                    "Retrying ..."
                )
                time.sleep(attempt)
                continue

            print("Request failed")
            print(f"Status: {status}")
            print(f"URL: {url}")
            # 有些响应可能不是文本，这里用 repr 防止编码报错
            print(f"Body: {repr(body)}")
            raise e

    # 理论上走不到这里
    if last_exc is not None:
        raise last_exc
    raise Exception("Request failed without specific exception")


def choice_validate(options: list[str], message: str) -> int:
    """
    让用户在给定 options 里选一个数字（字符串形式），
    返回选中的 int 值。
    """
    while True:
        user_choice = input(message).strip()
        if user_choice in options:
            return int(user_choice)
        else:
            print("Invalid input. Try again.")


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
    no_list: list[str] = []

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


def list_lessons_for_course(ed_url: str, token: str, course_id: int) -> list[dict]:
    """
    调 /courses/<course_id>/lessons，
    按 lesson_id (id) 排序后打印出来，并返回排序后的 lessons 列表。
    """
    lessons_url = f"{ed_url}/courses/{course_id}/lessons"
    r = request("GET", lessons_url, headers={"Authorization": "Bearer " + token})
    data = r.json()

    # 官方结构大概是 {"lessons": [...], "modules": [...]}
    lessons = data.get("lessons", data)  # 保险一点：有的环境可能直接就是 list

    # ---- 新增：空 lesson 检查 ----
    if not lessons:
        print("\n=== This course has NO lessons on Ed ===\n")
        return []

    # ---- 核心：按 lesson_id 排序 ----
    lessons_sorted = sorted(
        lessons,
        key=lambda l: (l.get("id") is None, l.get("id") or 0),
    )

    print("=== Lessons in this course (sorted by lesson_id) ===")
    for idx, lesson in enumerate(lessons_sorted, start=1):
        lesson_id = lesson.get("id")
        title = lesson.get("title")
        ltype = lesson.get("type")          # general / python / go ...
        module_id = lesson.get("module_id")

        print(
            f"{idx:2d}. "
            f"[id={lesson_id}] "
            f"type={ltype:<8} "
            f"module={module_id:<6} "
            f"- {title}"
        )
    print()

    # 顺便输出一个各 type 统计，帮你了解分布
    type_counter: dict[str, int] = {}
    for lesson in lessons_sorted:
        t = lesson.get("type") or "unknown"
        type_counter[t] = type_counter.get(t, 0) + 1

    print("Lesson type summary:")
    for t, count in sorted(type_counter.items(), key=lambda x: x[0]):
        print(f"  {t}: {count}")
    print()

    return lessons_sorted


def fetch_module_name_map(ed_url: str, token: str, course_id: int) -> dict[int, str]:
    """
    尝试为 module_id 找到一个比较友好的名字。
    使用 /courses/<course_id>/lessons 返回中的 "modules" 字段。
    """
    try:
        url = f"{ed_url}/courses/{course_id}/lessons"
        r = request(
            "GET",
            url,
            headers={"Authorization": "Bearer " + token},
        )
        data = r.json()
    except Exception as e:
        print("Failed to fetch course modules:", e)
        return {}

    modules_list = []
    if isinstance(data, dict):
        modules_list = data.get("modules") or []

    module_map: dict[int, str] = {}
    for m in modules_list:
        mid = m.get("id")
        if mid is None:
            continue
        mname = m.get("name") or m.get("title") or f"module_{mid}"
        module_map[mid] = mname

    return module_map


def safe_name(name: str) -> str:
    """把课程名 / 模块名 / lesson 名清洗成比较安全的目录或文件名。"""
    if not name:
        return "untitled"
    # 去掉首尾空格
    name = name.strip()
    # 替换常见在文件名中有问题的字符
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    # 可以根据需要做进一步简化
    return name


def shift_markdown_headings(md: str, offset: int = 1) -> str:
    """
    把 Markdown 里的标题级别整体下移 offset。
    例如 offset=1 时: # -> ##, ## -> ###, 最多到 ######。
    """
    if not md:
        return ""

    lines = []
    for line in md.splitlines():
        if line.startswith("#"):
            i = 0
            while i < len(line) and line[i] == "#":
                i += 1
            # 只处理形如 "### " 的行
            if i > 0 and i < 7 and (len(line) == i or line[i] == " "):
                new_level = min(6, i + offset)
                line = "#" * new_level + line[i:]
        lines.append(line)
    return "\n".join(lines)


def edxml_to_markdown(xml: str) -> str:
    """
    用 pypandoc 把 Ed 的 <document> XML 尽量转成 Markdown。
    - 做一点点 tag 替换，让它更接近 HTML，再交给 pandoc。
    - 如果 pandoc 崩了，就返回原始 XML。
    """
    if not xml:
        return ""

    # 粗略把 Ed XML 映射成 HTML-ish，Pandoc 认识 p / ul / li 这些标签
    html_like = (
        xml.replace("<document", "<div")
           .replace("</document>", "</div>")
           .replace("<paragraph", "<p")
           .replace("</paragraph>", "</p>")
           .replace("<heading", "<h")           # <heading level="1"> -> <h level="1"> (pandoc当普通标签处理，主要靠内容)
           .replace("</heading>", "</h>")
           .replace("<list ", "<ul ")
           .replace("</list>", "</ul>")
           .replace("<list-item", "<li")
           .replace("</list-item>", "</li>")
    )

    try:
        md = pypandoc.convert_text(html_like, "md", format="html")
    except Exception as e:
        # 万一 pandoc 崩了，也不要影响主流程
        print("pypandoc conversion failed:", e)
        return xml

    return md.strip()


def fetch_lesson_content(ed_url: str, token: str, lesson: dict) -> dict:
    """
    获取单个 lesson 的内容（slides）：
    - 先调用 /lessons/<lesson_id>?view=1 拿到 slides 列表
    - 再根据 slide.type:
        - document: 获取 content XML + 转成 Markdown
        - quiz: 获取 questions / responses / states，并简单转为 Markdown
        - 其他类型：先只记录基本信息
    返回结构化的 dict，并在 result["lesson_markdown"] 里附上拼好的整课 Markdown 文本。
    """
    lesson_id = lesson["id"]
    lesson_title = lesson.get("title")
    lesson_type = lesson.get("type")

    print(f"Fetching lesson {lesson_id} - {lesson_title!r}...")

    lesson_url = f"{ed_url}/lessons/{lesson_id}?view=1"
    r = request(
        "GET",
        lesson_url,
        headers={"Authorization": "Bearer " + token},
    )
    data = r.json()
    lesson_detail = data.get("lesson", data)
    slides = lesson_detail.get("slides") or []

    processed_slides: list[dict] = []

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
        slide_data = rs.json().get("slide", rs.json())
        stype = slide_data.get("type")

        # 公共元信息
        base_info = {
            "id": slide_id,
            "type": stype,
            "title": slide_data.get("title"),
            "index": slide_data.get("index"),
        }

        if stype == "document":
            # 普通文档 slide：content 里是 XML
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
            # quiz slide：题目在 /questions，作答在 /questions/responses，状态在 /questions/states
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
                    "passage": slide_data.get("passage"),  # quiz slide 自己的 passage（可能为空）
                    "questions": questions,
                    "responses": responses,
                    "states": states,
                }
            )
        else:
            # 其它类型先占个坑，后面想处理再加分支（pdf / code / html 等）
            processed_slides.append(base_info)

    # ----- 把整个 lesson 拼成一个 Markdown -----
    # 按 slide.index 排一下，避免 API 顺序奇怪
    processed_slides_sorted = sorted(
        processed_slides,
        key=lambda s: (s.get("index") is None, s.get("index") or 0),
    )

    md_parts: list[str] = []
    for slide in processed_slides_sorted:
        slide_title = slide.get("title") or f"Slide {slide.get('index')}"
        slide_type = slide.get("type")

        # 每个 slide 一个一级标题
        md_parts.append(f"# {slide_title}\n")

        if slide_type == "document":
            content_md = slide.get("content_md") or ""
            content_md = shift_markdown_headings(content_md, offset=1)
            if content_md:
                md_parts.append(content_md)
            md_parts.append("")  # 空行分隔

        elif slide_type == "quiz":
            # 简单把 quiz 的 passage + 题干 + 选项转成 Markdown
            passage_xml = slide.get("passage") or ""
            passage_md = edxml_to_markdown(passage_xml)
            passage_md = shift_markdown_headings(passage_md, offset=1)
            if passage_md:
                md_parts.append(passage_md)
                md_parts.append("")

            questions = slide.get("questions") or []
            for q in questions:
                q_data = q.get("data") or {}
                q_content_xml = q_data.get("content") or ""
                q_content_md = edxml_to_markdown(q_content_xml)
                q_content_md = shift_markdown_headings(q_content_md, offset=1)

                md_parts.append("## Question")
                if q_content_md:
                    md_parts.append(q_content_md)

                q_type = q_data.get("type")
                if q_type == "multiple-choice":
                    answers_xml_list = q_data.get("answers") or []
                    md_parts.append("")
                    md_parts.append("Options:")
                    for ans_xml in answers_xml_list:
                        ans_md = edxml_to_markdown(ans_xml)
                        ans_md = shift_markdown_headings(ans_md, offset=1)
                        md_parts.append(f"- {ans_md}")
                md_parts.append("")

        else:
            # 其它类型简单标记一下
            md_parts.append(f"_Slide type `{slide_type}` is not yet exported._")
            md_parts.append("")

    lesson_markdown = "\n".join(md_parts).rstrip() + "\n"

    result = {
        "lesson_meta": {
            "id": lesson_id,
            "title": lesson_title,
            "type": lesson_type,
        },
        "slides": processed_slides_sorted,
        "lesson_markdown": lesson_markdown,
    }

    return result


def lesson_download(ed_url: str, token: str):
    """
    主流程：
    1. 选课
    2. 拿到并打印按 lesson_id 排序的 lesson 列表
    3. 为该课程的所有 lesson 拉取内容，并按:
       ./<course_code> <course_name>/<module_name>/<lesson_name>.md
       的目录结构写入 Markdown 文件。
    """

    selected_course = select_course(ed_url, token)
    course = selected_course["course"]
    course_id = course["id"]
    course_code = course.get("code") or f"course_{course_id}"
    course_name = course.get("name") or ""
    course_dir_name = safe_name(f"{course_code} {course_name}".strip())
    base_dir = os.path.join(os.getcwd(), course_dir_name)

    # 预先拉 module 名字映射
    module_name_map = fetch_module_name_map(ed_url, token, course_id)

    lessons_sorted = list_lessons_for_course(ed_url, token, course_id)

    if not lessons_sorted:
        print("No lessons found for this course.")
        return

    print(f"Base output directory: {base_dir}")
    os.makedirs(base_dir, exist_ok=True)

    for lesson in lessons_sorted:
        lesson_id = lesson.get("id")
        lesson_title = lesson.get("title") or f"lesson_{lesson_id}"
        module_id = lesson.get("module_id")
        module_name = module_name_map.get(module_id, f"module_{module_id}")
        module_dir_name = safe_name(module_name)
        lesson_file_name = safe_name(lesson_title) + ".md"

        out_dir = os.path.join(base_dir, module_dir_name)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, lesson_file_name)

        # 获取 lesson 内容并写文件
        result = fetch_lesson_content(ed_url, token, lesson)
        lesson_md = result.get("lesson_markdown", "")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(lesson_md)

        print(f"Saved lesson {lesson_id} -> {out_path}")

    print("\nAll lessons downloaded.")


def main():
    ed_url = ED_HOST
    # 例如：import os; token = os.environ["ED_PAT"]
    token = "byVGl_.CG7HsNiPyPDGcxRbc5qX6nP2yIyQNjfGnDZ7ivNh"  # 在这里填你的 PAT
    if not token:
        print("Please set your Ed PAT in the 'token' variable.")
        return
    lesson_download(ed_url, token)


if __name__ == "__main__":
    main()