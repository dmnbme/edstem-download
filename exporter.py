import os
from pathlib import Path
from typing import Dict, List

from ed_client import EdClient, safe_filename
from converters import edxml_to_markdown


def fetch_lesson_content(client: EdClient, lesson: dict, image_resolver=None) -> dict:
    """
    Get slides of a lesson, returns structured dict.
    """
    lesson_id = lesson["id"]
    lesson_title = lesson.get("title")
    lesson_type = lesson.get("type")

    print(f"Fetching lesson {lesson_id} - {lesson_title!r} (type={lesson_type}) ...")

    lesson_detail = client.fetch_lesson_detail(lesson_id)
    slides = lesson_detail.get("slides") or []

    processed_slides: List[dict] = []

    for s in slides:
        slide_id = s.get("id")
        if slide_id is None:
            continue

        slide_data = client.fetch_slide_detail(slide_id)
        stype = slide_data.get("type")

        base_info = {
            "id": slide_id,
            "type": stype,
            "title": slide_data.get("title"),
            "index": slide_data.get("index"),
        }

        if stype == "document":
            content_xml = slide_data.get("content") or ""
            content_md = edxml_to_markdown(
                content_xml,
                image_resolver=image_resolver,
            )
            processed_slides.append(
                {
                    **base_info,
                    "content_xml": content_xml,
                    "content_md": content_md,
                }
            )

        elif stype == "quiz":
            questions, responses, states = client.fetch_quiz_data(slide_id)
            processed_slides.append(
                {
                    **base_info,
                    "passage": slide_data.get("passage"),
                    "questions": questions,
                    "responses": responses,
                    "states": states,
                }
            )
        elif stype == "pdf":
            processed_slides.append(
                {
                    **base_info,
                    "file_url": slide_data.get("file_url"),
                }
            )
        elif stype == "code":
            content_xml = slide_data.get("content") or ""
            content_md = edxml_to_markdown(
                content_xml,
                image_resolver=image_resolver,
            )
            explanation_md = ""
            challenge_id = slide_data.get("challenge_id")
            if isinstance(challenge_id, int):
                try:
                    challenge = client.fetch_challenge_detail(challenge_id)
                    explanation_xml = challenge.get("explanation") or ""
                    if explanation_xml:
                        explanation_md = edxml_to_markdown(
                            explanation_xml,
                            image_resolver=image_resolver,
                        )
                except Exception as e:
                    print(f"Failed to fetch challenge {challenge_id}: {e}")

            processed_slides.append(
                {
                    **base_info,
                    "content_xml": content_xml,
                    "content_md": content_md,
                    "explanation_md": explanation_md,
                }
            )
        else:
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
    course_root: Path,
    module_name_map: Dict[int, str],
    lesson: dict,
    lesson_struct: dict,
    assets_resolver=None,
) -> None:
    """
    Write all the slides of a lesson into a markdown file.
    """
    module_id = lesson.get("module_id")
    if isinstance(module_id, int):
        module_name = module_name_map.get(module_id, f"module_{module_id}")
    else:
        module_name = "module_unknown"

    lesson_title = lesson.get("title") or f"lesson_{lesson['id']}"

    module_dir = Path(course_root) / safe_filename(module_name)
    module_dir.mkdir(parents=True, exist_ok=True)

    file_path = module_dir / f"{safe_filename(lesson_title)}.md"

    parts: List[str] = []

    for slide in lesson_struct.get("slides", []):
        stitle = slide.get("title") or f"Slide {slide.get('index')}"
        stype = slide.get("type")

        parts.append(f"# {stitle}")

        if stype == "document":
            body = slide.get("content_md") or ""
            if body:
                parts.append(body)
        elif stype == "quiz":
            parts.append("_Quiz slide: questions/responses not converted to markdown yet._")
        elif stype == "pdf":
            file_url = slide.get("file_url") or "(missing pdf url)"
            if assets_resolver:
                file_url = assets_resolver(file_url)
            label = Path(file_url).name if file_url else "PDF"
            parts.append(f"[{label}]({file_url})")
        elif stype == "code":
            body = slide.get("content_md") or ""
            if body:
                parts.append(body)
            explanation_md = slide.get("explanation_md") or ""
            if explanation_md:
                solution_title = f"# {stitle} - Solution"
                parts.append(solution_title)
                parts.append(explanation_md)
        else:
            parts.append(f"_Slide of type `{stype}` not converted (code/pdf/etc)._")

    md_text = "\n\n".join(parts) + "\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"  -> saved markdown to {file_path}")
