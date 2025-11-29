import base64
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import urlparse

import filetype
import requests

class EdApiError(Exception):
    pass


def request(
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    **kwargs: Any,
) -> requests.Response:
    """A simple wrap of requests.request with retry"""
    last_exception: Exception | None = None

    for attempt in range(1, retries + 1):
        status = ""
        body_repr = ""

        try:
            resp = requests.request(method, url, **kwargs)
            status = str(resp.status_code)

            try:
                body_repr = repr(resp.text)
            except Exception:
                body_repr = "<non-text response>"

            if 200 <= resp.status_code <= 299:
                return resp

            if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                if attempt < retries:
                    print(
                        f"Request got bad status {resp.status_code}, "
                        f"retrying ({attempt}/{retries})..."
                    )
                    time.sleep(backoff * attempt)
                    continue

            raise EdApiError(f"Bad status code: {resp.status_code}")

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
                raise

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected request() failure")


def choice_validate(options: List[str], message: str) -> int:
    """
    Prompt the user choose a number from `options`, 
    showing `message`,
    return int value of the chosen one.
    """
    while True:
        user_choice = input(message).strip()
        if user_choice in options:
            return int(user_choice)
        else:
            print("Invalid input. Try again.")


def safe_filename(name: str) -> str:
    """
    Convert course / module / lesson name into safe name 
    without special chars for OS display.
    """
    if not name:
        return "unnamed"

    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name


class EdClient:
    """
    Interactions with Ed API.
    """

    def __init__(self, token: str, base_url: str) -> None:
        if not token:
            raise ValueError("Ed PAT token is required")
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": "Bearer " + token}
        # cache downloaded images to avoid duplicates
        # value: (content, mime from response header or None)
        self._image_cache: Dict[str, Tuple[bytes, str | None]] = {}

    def _download_image_bytes(self, src: str) -> Tuple[bytes, str | None] | None:
        if src in self._image_cache:
            return self._image_cache[src]
        try:
            resp = requests.get(src, timeout=10)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type")
            self._image_cache[src] = (resp.content, content_type)
            return resp.content, content_type
        except Exception as e:
            print(f"Image download failed for {src}: {e}")
            return None

    def make_image_resolver(
        self,
        mode: str,
        *,
        image_dir: Path | None = None,
        markdown_dir: Path | None = None,
    ) -> Callable[[str], str]:
        """
        Return a callable that maps image src -> processed src according
        to the configured mode: base64 | file | url.
        """
        mode = (mode or "base64").lower()
        cache: Dict[str, str] = {}

        def _infer_ext(src: str, content: bytes | None, header_mime: str | None) -> str:
            # 1) try response header mime
            if header_mime:
                guessed = mimetypes.guess_extension(header_mime)
                if guessed:
                    return guessed
                if header_mime.startswith("image/"):
                    return ".jpg"

            # 2) try mimetype from URL
            url_mime = mimetypes.guess_type(src)[0]
            if url_mime:
                guessed = mimetypes.guess_extension(url_mime)
                if guessed:
                    return guessed

            # 3) inspect bytes with filetype
            if content:
                kind = filetype.guess(content)
                if kind and kind.extension:
                    return f".{kind.extension}"

            # 4) fall back to URL suffix if present
            parsed = urlparse(src)
            suffix = os.path.splitext(parsed.path)[1].lower()
            if suffix and suffix not in {".bin", ".dat"}:
                return suffix

            # 5) safest default for images
            return ".jpg"

        def resolve(src: str) -> str:
            if not src:
                return ""
            if src in cache:
                return cache[src]

            result = src  # fallback

            if mode == "url":
                result = src

            elif mode == "base64":
                download = self._download_image_bytes(src)
                if download is not None:
                    content, header_mime = download
                    mime = header_mime or mimetypes.guess_type(src)[0]
                    if not mime:
                        kind = filetype.guess(content)
                        mime = kind.mime if kind and kind.mime else "application/octet-stream"
                    b64 = base64.b64encode(content).decode("ascii")
                    result = f"data:{mime};base64,{b64}"

            elif mode == "file" and image_dir:
                download = self._download_image_bytes(src)
                if download is not None:
                    content, header_mime = download
                    ext = _infer_ext(src, content, header_mime)
                    filename = f"img{len(cache)+1:03d}{ext}"
                    target = image_dir / filename
                    if not target.parent.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    rel_base = markdown_dir if markdown_dir else image_dir
                    result = os.path.relpath(target, rel_base)

            cache[src] = result
            return result

        return resolve

    def get_courses(self) -> List[dict]:
        r = request("GET", self.base_url + "/user", headers=self._headers)
        u = r.json()
        return sorted(u["courses"], key=lambda x: x["course"]["code"])

    def select_course_interactive(self) -> dict:
        courses = self.get_courses()
        no_list: List[str] = []

        print("\n=== Your courses on Ed ===")
        for idx, c in enumerate(courses, start=1):
            code = c["course"]["code"]
            name = c["course"]["name"]
            print(f"{idx}. {code} {name}")
            no_list.append(str(idx))

        choice = choice_validate(no_list, "\nSelect the course you want to download: ")
        selected_course = courses[choice - 1]
        print(
            f"\nYou selected: {selected_course['course']['code']} "
            f"{selected_course['course']['name']}\n"
        )
        return selected_course

    def list_lessons_for_course(
        self,
        course_id: int,
    ) -> Tuple[List[dict], Dict[int, str]]:
        """
        return tuple including list of lessons, and dict of module_id and module_name
        """

        lessons_url = f"{self.base_url}/courses/{course_id}/lessons"
        r = request("GET", lessons_url, headers=self._headers)
        data = r.json()

        lessons = data.get("lessons", [])
        modules_list = data.get("modules", [])

        if not lessons:
            print("This course currently has no lessons (API returned an empty list).")
            return [], {}

        lessons_sorted = sorted(
            lessons,
            key=lambda l: (l.get("id") is None, l.get("id") or 0),
        )

        print("=== Lessons in this course (sorted by lesson_id) ===")
        for idx, lesson in enumerate(lessons_sorted, start=1):
            lesson_id = lesson.get("id")
            title = lesson.get("title")
            ltype = lesson.get("type")
            module_id = lesson.get("module_id")

            print(
                f"{idx:2d}. "
                f"[id={lesson_id}] "
                f"type={ltype:<8} "
                f"module={module_id:<6} "
                f"- {title}"
            )
        print()

        type_counter: Dict[str, int] = {}
        for lesson in lessons_sorted:
            t = lesson.get("type") or "unknown"
            type_counter[t] = type_counter.get(t, 0) + 1

        print("Lesson type summary:")
        for t, count in sorted(type_counter.items(), key=lambda x: x[0]):
            print(f"  {t}: {count}")
        print()

        module_name_map: Dict[int, str] = {}
        for m in modules_list:
            mid = m.get("id")
            if isinstance(mid, int):
                mname = m.get("name") or m.get("title") or f"module_{mid}"
                module_name_map[mid] = mname

        return lessons_sorted, module_name_map

    def fetch_lesson_detail(self, lesson_id: int) -> dict:
        lesson_url = f"{self.base_url}/lessons/{lesson_id}?view=1"
        r = request("GET", lesson_url, headers=self._headers)
        data = r.json()
        return data.get("lesson", data)

    def fetch_slide_detail(self, slide_id: int) -> dict:
        slide_url = f"{self.base_url}/lessons/slides/{slide_id}?view=1"
        rs = request("GET", slide_url, headers=self._headers)
        slide_json = rs.json()
        return slide_json.get("slide", slide_json)

    def fetch_quiz_data(self, slide_id: int) -> Tuple[Any, Any, Any]:
        q_base = f"{self.base_url}/lessons/slides/{slide_id}/questions"

        rq = request("GET", q_base, headers=self._headers)
        rr = request("GET", q_base + "/responses", headers=self._headers)
        rs2 = request("GET", q_base + "/states", headers=self._headers)

        questions = rq.json().get("questions", rq.json())
        responses = rr.json().get("responses", rr.json())
        states = rs2.json().get("states", rs2.json())

        return questions, responses, states
