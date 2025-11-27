import sys
from pathlib import Path

from config import ED_HOST, get_token
from ed_client import EdClient, safe_filename
from exporter import fetch_lesson_content, save_lesson_markdown


def export_course_lessons_to_markdown(client: EdClient) -> None:
    selected_course = client.select_course_interactive()
    course_info = selected_course["course"]
    course_id = course_info["id"]
    course_code = course_info["code"]
    course_name = course_info["name"]

    course_dir_name = safe_filename(f"{course_code} {course_name}")
    course_root = Path.cwd() / course_dir_name
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
        lesson_struct = fetch_lesson_content(client, lesson)
        save_lesson_markdown(str(course_root), module_name_map, lesson, lesson_struct)


def main() -> None:
    token = get_token()

    if not token:
        print("Please set your Ed API token in the ED_PAT environment variable, or in the config file.")
        sys.exit(1)

    client = EdClient(token=token, base_url=ED_HOST)
    export_course_lessons_to_markdown(client)


if __name__ == "__main__":
    main()
