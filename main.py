import sys
from pathlib import Path

from config import load_config, get_ed_host, get_token, get_image_mode, get_output_dir
from ed_client import EdClient, safe_filename
from exporter import fetch_lesson_content, save_lesson_markdown


def export_course_lessons_to_markdown(
    client: EdClient,
    course_root: Path,
    image_mode: str,
) -> None:
    selected_course = client.select_course_interactive()
    course_info = selected_course["course"]
    course_id = course_info["id"]
    course_code = course_info["code"]
    course_name = course_info["name"]

    course_dir_name = safe_filename(f"{course_code} {course_name}")
    course_root = course_root / course_dir_name
    course_root.mkdir(parents=True, exist_ok=True)

    lessons_sorted, module_name_map = client.list_lessons_for_course(course_id)
    if not lessons_sorted:
        return

    total = len(lessons_sorted)
    for idx, lesson in enumerate(lessons_sorted, start=1):
        print(
            f"\n=== [{idx}/{total}] Processing lesson id={lesson['id']} "
            f"- {lesson.get('title')!r} ==="
        )
        module_id = lesson.get("module_id")
        if isinstance(module_id, int):
            module_name = module_name_map.get(module_id, f"module_{module_id}")
        else:
            module_name = "module_unknown"

        module_dir = course_root / safe_filename(module_name)
        image_dir = module_dir / "images"
        image_resolver = client.make_image_resolver(
            image_mode,
            image_dir=image_dir,
            markdown_dir=module_dir,
        )

        lesson_struct = fetch_lesson_content(
            client,
            lesson,
            image_resolver=image_resolver,
        )
        save_lesson_markdown(course_root, module_name_map, lesson, lesson_struct)


def main() -> None:
    cfg = load_config()  # 默认读取 ./config.toml
    base_url = get_ed_host(cfg)
    token = get_token(cfg)
    image_mode = get_image_mode(cfg)
    output_dir = get_output_dir(cfg)

    client = EdClient(token=token, base_url=base_url)
    export_course_lessons_to_markdown(client, output_dir, image_mode)


if __name__ == "__main__":
    main()
