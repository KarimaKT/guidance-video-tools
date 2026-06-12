"""
CAT Video Tools — Web UI
=========================
Streamlit-based interface for both tools:
  1. Meeting Sanitizer: upload recording + transcript → get clean video
  2. Demo Video Creator: describe a demo or web walkthrough → get a narrated MP4

Run:
    streamlit run app.py
"""

import streamlit as st
import sys
import os
import tempfile
import shutil
import zipfile
import subprocess
from pathlib import Path
import yaml

# Add tool directories to path
ROOT = Path(__file__).parent
TEST_DIR = ROOT / "test"
sys.path.insert(0, str(ROOT / "sanitizer"))
sys.path.insert(0, str(ROOT / "creator"))


def _resolve_demo_path(path_value: str) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _demo_media_path(demo: dict) -> Path | None:
    return _resolve_demo_path(demo.get("media") or demo.get("video") or "")


def _demo_thumbnail_path(demo: dict) -> Path | None:
    return _resolve_demo_path(demo.get("thumbnail", ""))


def _demo_display_title(demo: dict) -> str:
    title = demo.get("title", "Untitled demo")
    replacements = {
        "Better demo: ": "",
        "Better clip: ": "",
        "Standalone course video: ": "",
        "Creator Demo Video Creator": "Demo Video Creator",
        "Creator Video Creator": "Video Creator",
        "Clip Clip Extractor": "Clip Extractor",
        "Sanitizer Meeting Sanitizer": "Meeting Sanitizer",
        "Technical Technical Explainer": "Technical Explainer",
    }
    for old, new in replacements.items():
        title = title.replace(old, new)
    return title


def _demo_group(demo: dict) -> str:
    status = str(demo.get("status", "")).lower()
    if demo.get("created_video"):
        if demo.get("example") and not demo.get("featured"):
            return "Example outputs"
        if _is_final_created_video(demo) and demo.get("featured"):
            return "Featured videos"
        return "Created videos"
    if "web walkthrough" in status:
        return "Web walkthroughs"
    if "better demo - generated" in status:
        return "Featured app demos"
    if "standalone learning series" in status:
        return "Evaluation learning series"
    if "webinar clip" in status:
        return "Generated clips"
    if "reference" in status:
        return "References"
    return "Legacy samples"


def _created_video_status(demo: dict) -> str:
    return str(demo.get("production_status") or demo.get("review_status") or "draft").lower()


def _is_final_created_video(demo: dict) -> bool:
    return _created_video_status(demo) == "final"


def _created_video_tool(demo: dict) -> str:
    return str(demo.get("tool") or demo.get("kind") or "Other").replace("_", " ")


def _created_video_topic(demo: dict) -> str:
    tags = [str(tag) for tag in demo.get("tags", [])]
    if demo.get("topic"):
        return str(demo["topic"])
    if tags:
        return tags[0].replace("-", " ")
    return "General"


def _friendly_demo_label(demo: dict) -> str:
    status = str(demo.get("status", "")).lower()
    kind = str(demo.get("kind", "demo")).replace("_", " ")
    if demo.get("created_video"):
        return f"{_created_video_tool(demo)} · {_created_video_topic(demo)} · {_created_video_status(demo)}"
    if "web walkthrough" in status:
        return "web walkthrough · narrated product tour"
    if "better demo - generated" in status:
        return f"{kind} · current app demo"
    if "webinar clip" in status:
        return "clip · webinar reference"
    if "standalone learning series" in status:
        return "technical explainer · learning series"
    if "current app demo" in status:
        return f"{kind} · legacy sample"
    if "reference" in status:
        return f"{kind} · reference"
    return f"{kind} · {demo.get('status', 'demo')}"


def _load_demo_manifest() -> dict:
    manifest_path = TEST_DIR / "demo_manifest.yaml"
    if not manifest_path.exists():
        return {"demos": []}
    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"demos": []}


def _skill_callout(title: str, body: str, prompt: str) -> None:
    """Render a consistent bridge from Clawpilot skills back into the app."""
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.write(body)
        st.code(prompt.strip() + "\n", language="text")


WORKFLOW_ORDER = {
    "sanitizer": 0,
    "clip extraction": 1,
    "creator": 2,
    "web walkthrough": 2,
    "technical explainer": 3,
}


def _workflow_order_key(demo: dict) -> tuple[int, str]:
    return (WORKFLOW_ORDER.get(str(demo.get("kind", "")).lower(), 99), _demo_display_title(demo))


def _first_demo_for(demos: list[dict], kind: str) -> dict | None:
    kind = kind.lower()
    for demo in sorted(demos, key=_workflow_order_key):
        if str(demo.get("kind", "")).lower() == kind and "better demo - generated" in str(demo.get("status", "")):
            return demo
    return None


def _parse_segments(text: str) -> list:
    """Parse segment text like '6:09 - 66:57' into [(start_sec, end_sec), ...]"""
    import re
    segments = []
    for line in text.strip().split("\n"):
        line = line.split("#")[0].strip()
        if not line:
            continue
        match = re.match(r'(\d+:?\d+:?\d*)\s*[-–]\s*(\d+:?\d+:?\d*)', line)
        if match:
            start = _parse_time(match.group(1))
            end = _parse_time(match.group(2))
            if start is not None and end is not None:
                segments.append((start, end))
    return segments if segments else None


def _parse_time(t: str) -> float:
    """Parse MM:SS or H:MM:SS to seconds."""
    parts = t.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return None


def _fmt_time(sec: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _parse_clip_specs(text: str):
    """Parse clip lines as start - end | title | optional category."""
    from clip_extractor import ClipSpec, safe_clip_id

    clips = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        time_part = parts[0]
        if "-" not in time_part:
            continue
        start_text, end_text = [p.strip() for p in time_part.split("-", 1)]
        start = _parse_time(start_text)
        end = _parse_time(end_text)
        if start is None or end is None or end <= start:
            continue
        title = parts[1] if len(parts) > 1 and parts[1] else f"Clip {_fmt_time(start)}"
        category = parts[2] if len(parts) > 2 else ""
        clips.append(ClipSpec(
            id=safe_clip_id(title),
            title=title,
            start=start,
            end=end,
            category=category,
            manual=True,
        ))
    return clips


def _split_lines(text: str) -> list[str]:
    return [
        line.strip().lstrip("-•0123456789. ").strip()
        for line in text.splitlines()
        if line.strip()
    ]


def _draft_video_scenes(topic: str, audience: str, key_points: str, duration: str) -> list[dict]:
    """Create an editable first draft from a brief.

    This is intentionally deterministic so the user can review and change every
    scene before rendering. A model-backed drafter can replace this later.
    """
    points = _split_lines(key_points)
    if not points:
        points = [
            "What problem the viewer has",
            "What the tool does differently",
            "What the viewer should do next",
        ]

    scene_count = {
        "30 seconds": 3,
        "60 seconds": 4,
        "90 seconds": 4,
        "2 minutes": 5,
        "3 minutes": 6,
        "5 minutes": 7,
    }.get(duration, 4)

    audience_text = audience or "the intended audience"
    scenes = [
        {
            "title": topic[:72] or "Untitled explainer",
            "narration": (
                f"This video is for {audience_text}. It explains {topic.strip()} "
                "in a way that is practical, visual, and ready to review before publishing."
            ),
            "bullets": "\n".join(points[:3]),
            "layout": "Title card",
            "style": "Executive dark",
        },
        {
            "title": "Why it matters",
            "narration": (
                f"The important point is not just the feature. It is what changes for {audience_text}: "
                "less manual work, clearer decisions, and a more reliable path from idea to output."
            ),
            "bullets": "\n".join(points[:3]),
            "layout": "Two-column",
            "style": "Executive dark",
        },
        {
            "title": "How the workflow works",
            "narration": (
                "The workflow keeps humans in control. Draft the structure, review the script, "
                "adjust the scenes, and only then render the final video."
            ),
            "bullets": "Draft\nReview\nEdit\nGenerate\nValidate",
            "layout": "Process",
            "style": "Coral energy",
        },
        {
            "title": "Ready to generate",
            "narration": (
                "Before generation, inspect the title, narration, bullet points, voice, and style. "
                "That review step is what makes the output useful instead of just automated."
            ),
            "bullets": "Editable script\nProfessional slides\nClean narration\nValidated output",
            "layout": "Checklist",
            "style": "Berry premium",
        },
    ]

    for point in points[3:scene_count - 1]:
        scenes.insert(
            -1,
            {
                "title": point[:64],
                "narration": f"One key point to cover is {point}. This scene should make the idea concrete with a visual example and a clear takeaway.",
                "bullets": point,
                "layout": "Spotlight",
                "style": "Berry premium",
            },
        )

    return scenes[:scene_count]


def _default_web_walkthrough_steps(url: str) -> list[dict]:
    return [
        {
            "label": "Open the portal",
            "action": "goto",
            "narration": "Introducing CAT Video Tools, the local portal for production-ready video workflows.",
        },
        {
            "label": "Show featured demos",
            "action": "scroll:0.28",
            "narration": "The front page leads with generated demos, not abstract promises.",
        },
        {
            "label": "Show workflows",
            "action": "scroll:0.62",
            "narration": "The workflow cards separate cleanup, clipping, demo videos, and teaching videos.",
        },
        {
            "label": "Open Test Gallery",
            "action": "click:Test Gallery",
            "narration": "The Test Gallery is the review surface for generated outputs.",
        },
        {
            "label": "Open Meeting Sanitizer",
            "action": "click:Meeting Sanitizer",
            "narration": "Meeting Sanitizer prepares recorded meetings for safer sharing.",
        },
        {
            "label": "Open Clip Extractor",
            "action": "click:Clip Extractor",
            "narration": "Clip Extractor turns long recordings into intentional short clips.",
        },
        {
            "label": "Open Demo Video Creator",
            "action": "click:Demo Video Creator",
            "narration": "Demo Video Creator turns scripts and web steps into narrated tours.",
        },
        {
            "label": "Show web walkthrough feature",
            "action": "wait",
            "narration": "Paste a page, list the steps, then generate the narrated walkthrough.",
        },
        {
            "label": "Open Technical Explainer Studio",
            "action": "click:Technical Explainer Studio",
            "narration": "Technical Explainer Studio is for deeper, source-grounded teaching videos.",
        },
    ]


def _format_walkthrough_steps(steps: list[dict]) -> str:
    return "\n".join(
        f"{step['label']} | {step['action']} | {step['narration']}"
        for step in steps
    )


def _parse_walkthrough_steps(text: str) -> list[dict]:
    steps = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) != 3:
            continue
        label, action, narration = parts
        if label and action and narration:
            steps.append({"label": label, "action": action, "narration": narration})
    return steps


def _walkthrough_plan_yaml(title: str, url: str, max_seconds: float, voice: str, voice_rate: str, steps: list[dict]) -> str:
    data = {
        "title": title,
        "url": url,
        "max_screen_seconds": max_seconds,
        "voice": voice.split(" (")[0],
        "voice_rate": voice_rate,
        "steps": steps,
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _sample_video_script_yaml() -> str:
    data = {
        "title": "Sample Demo Video",
        "resolution": "1280x720",
        "fps": 30,
        "voice": "en-US-AriaNeural",
        "voice_rate": "+5%",
        "music_volume": 0,
        "scenes": [
            {
                "title": "Introducing the demo",
                "subtitle": "What this video shows and why it matters",
                "visual": "slide",
                "narration": "Use the first scene to orient the viewer. Name the app or feature, explain what it does, and give the viewer a reason to keep watching.",
                "bullets": [
                    "What was built",
                    "Who it helps",
                    "What the viewer will see",
                ],
                "background": "#0f172a",
                "text_color": "#ffffff",
                "accent_color": "#93c5fd",
                "animation": "fade_in",
            },
            {
                "title": "Show the workflow",
                "subtitle": "Use an embedded screenshot or video clip",
                "visual": "video",
                "video": "C:\\path\\to\\walkthrough-or-demo-clip.mp4",
                "narration": "",
                "bullets": [],
                "background": "#111827",
                "accent_color": "#60a5fa",
                "animation": "none",
            },
            {
                "title": "Land the takeaway",
                "subtitle": "Close with what the viewer can do next",
                "visual": "slide",
                "narration": "End with the outcome, not a generic recap. Tell the viewer what they are now prepared to do in their own project.",
                "bullets": [
                    "Review before rendering",
                    "Keep clips intentional",
                    "Validate the output",
                ],
                "background": "#312e81",
                "text_color": "#ffffff",
                "accent_color": "#fbbf24",
                "animation": "slide_up",
            },
        ],
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _scene_visuals(style: str, layout: str) -> dict:
    palettes = {
        "Executive dark": {"background": "#111827", "accent_color": "#60a5fa", "text_color": "#ffffff"},
        "Coral energy": {"background": "#2F3C7E", "accent_color": "#F96167", "text_color": "#ffffff"},
        "Berry premium": {"background": "#6D2E46", "accent_color": "#ECE2D0", "text_color": "#ffffff"},
        "Clean light": {"background": "#FCF6F5", "accent_color": "#990011", "text_color": "#2F3C7E"},
    }
    visuals = palettes.get(style, palettes["Executive dark"]).copy()
    visuals["animation"] = "slide_up" if layout in {"Process", "Checklist"} else "fade_in"
    return visuals


def _build_video_script(title: str, voice: str, voice_rate: str, scenes: list[dict]):
    from video_creator import VideoScript, Scene as VScene

    script = VideoScript()
    script.title = title
    script.voice = voice.split(" (")[0]
    script.voice_rate = voice_rate

    for s in scenes:
        if not s.get("narration"):
            continue
        scene = VScene()
        scene.title = s.get("title", "")
        scene.subtitle = s.get("layout", "")
        scene.narration = s.get("narration", "")
        scene.bullets = _split_lines(s.get("bullets", ""))
        scene.visual = "video" if s.get("video_path") else "image" if s.get("image_path") else "slide"
        scene.image_path = s.get("image_path", "")
        scene.video_path = s.get("video_path", "")
        for key, value in _scene_visuals(s.get("style", "Executive dark"), s.get("layout", "Title card")).items():
            setattr(scene, key, value)
        script.scenes.append(scene)
    return script


def _script_yaml(title: str, voice: str, voice_rate: str, scenes: list[dict]) -> str:
    data = {
        "title": title,
        "voice": voice.split(" (")[0],
        "voice_rate": voice_rate,
        "scenes": [
            {
                "title": s.get("title", ""),
                "subtitle": s.get("layout", ""),
                "narration": s.get("narration", ""),
                "bullets": _split_lines(s.get("bullets", "")),
                "visual": "video" if s.get("video_path") else "image" if s.get("image_path") else "slide",
                "image": s.get("image_path", ""),
                "video": s.get("video_path", ""),
                **_scene_visuals(s.get("style", "Executive dark"), s.get("layout", "Title card")),
            }
            for s in scenes
            if s.get("narration") or s.get("video_path")
        ],
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _brand_dir() -> Path:
    path = ROOT / "branding"
    path.mkdir(exist_ok=True)
    return path


def _export_first_pptx_slide(pptx_path: Path, output_path: Path) -> Path | None:
    try:
        import win32com.client
    except Exception:
        return None

    app = win32com.client.Dispatch("PowerPoint.Application")
    presentation = None
    try:
        presentation = app.Presentations.Open(str(pptx_path), WithWindow=False)
        presentation.Slides(1).Export(str(output_path), "PNG", 1280, 720)
        return output_path if output_path.exists() else None
    finally:
        if presentation is not None:
            presentation.Close()
        app.Quit()


def _save_brand_asset(uploaded_file) -> dict | None:
    if not uploaded_file:
        return st.session_state.get("brand_asset")

    ext = Path(uploaded_file.name).suffix.lower()
    brand_root = _brand_dir()
    source_path = brand_root / f"current{ext}"
    source_path.write_bytes(uploaded_file.getbuffer())

    asset = {
        "name": uploaded_file.name,
        "source_path": str(source_path),
        "type": ext.lstrip("."),
        "title_image": None,
    }

    if ext in {".png", ".jpg", ".jpeg"}:
        asset["title_image"] = str(source_path)
    elif ext == ".pptx":
        image_path = brand_root / "current-title-slide.png"
        exported = _export_first_pptx_slide(source_path, image_path)
        if exported:
            asset["title_image"] = str(exported)

    st.session_state.brand_asset = asset
    return asset


def _apply_brand_title_scene(script, title: str, brand_asset: dict | None):
    if not brand_asset or not brand_asset.get("title_image"):
        return
    from video_creator import Scene as VScene

    scene = VScene()
    scene.title = title
    scene.narration = ""
    scene.visual = "image"
    scene.image_path = brand_asset["title_image"]
    scene.duration = 2.5
    scene.animation = "fade_in"
    script.scenes.insert(0, scene)


def _make_card_video(
    *,
    title: str,
    subtitle: str,
    output_path: Path,
    duration: float = 3.0,
    style: str = "Executive dark",
):
    from video_creator import Scene as VScene, VideoCreator, VideoScript

    script = VideoScript()
    script.title = title
    script.resolution = (1280, 720)
    script.music_volume = 0

    scene = VScene()
    scene.title = title
    scene.subtitle = subtitle
    scene.narration = ""
    scene.duration = duration
    scene.bullets = []
    scene.visual = "slide"
    scene.animation = "fade_in"
    for key, value in _scene_visuals(style, "Title card").items():
        setattr(scene, key, value)
    script.scenes = [scene]

    VideoCreator(script=script).generate(str(output_path), verbose=False)
    return output_path


def _add_title_and_end_cards(
    *,
    source_video: str | Path,
    output_video: str | Path,
    title_text: str,
    subtitle_text: str,
    end_text: str,
):
    from media_pipeline import concat_videos

    source = Path(source_video)
    final = Path(output_video)
    parts = []
    if title_text.strip():
        title_card = final.parent / "title_card.mp4"
        parts.append(_make_card_video(
            title=title_text.strip(),
            subtitle=subtitle_text.strip(),
            output_path=title_card,
            duration=3.0,
            style="Executive dark",
        ))
    parts.append(source)
    if end_text.strip():
        end_card = final.parent / "ending_card.mp4"
        parts.append(_make_card_video(
            title=end_text.strip(),
            subtitle="",
            output_path=end_card,
            duration=3.0,
            style="Berry premium",
        ))
    if len(parts) == 1:
        shutil.copyfile(source, final)
    else:
        concat_videos(parts, final, crf=20)
    return final


def _asset_dir() -> Path:
    path = ROOT / "assets" / "current"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_asset_uploads(files, kind: str) -> list[dict]:
    saved = []
    if not files:
        return saved
    target_dir = _asset_dir() / kind
    target_dir.mkdir(parents=True, exist_ok=True)
    for uploaded in files:
        safe_name = Path(uploaded.name).name
        path = target_dir / safe_name
        path.write_bytes(uploaded.getbuffer())
        saved.append({"name": safe_name, "path": str(path), "kind": kind})
    return saved


def _scan_asset_folders(folder_text: str) -> list[dict]:
    assets = []
    image_exts = {".png", ".jpg", ".jpeg", ".webp"}
    video_exts = {".mp4", ".mkv", ".webm", ".mov"}
    doc_exts = {".txt", ".md", ".csv", ".log", ".docx", ".pptx"}
    for raw in folder_text.splitlines():
        folder = Path(raw.strip().strip('"'))
        if not folder.exists() or not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in image_exts:
                assets.append({"name": path.name, "path": str(path), "kind": "images"})
            elif ext in video_exts:
                assets.append({"name": path.name, "path": str(path), "kind": "videos"})
            elif ext in doc_exts:
                assets.append({"name": path.name, "path": str(path), "kind": "documents"})
    return assets


def _extract_office_text(path: Path) -> str:
    import html
    import re

    if path.suffix.lower() == ".docx":
        members = ["word/document.xml"]
    elif path.suffix.lower() == ".pptx":
        with zipfile.ZipFile(path) as archive:
            members = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
    else:
        return ""

    chunks = []
    with zipfile.ZipFile(path) as archive:
        for member in members:
            try:
                xml = archive.read(member).decode("utf-8", errors="ignore")
            except KeyError:
                continue
            text = re.sub(r"<[^>]+>", " ", xml)
            text = html.unescape(text)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _read_document_context(document_assets: list[dict], max_chars: int = 5000) -> str:
    chunks = []
    for asset in document_assets:
        path = Path(asset["path"])
        ext = path.suffix.lower()
        if ext not in {".txt", ".md", ".csv", ".log", ".docx", ".pptx"}:
            continue
        try:
            if ext in {".docx", ".pptx"}:
                text = _extract_office_text(path).strip()
            else:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except (OSError, zipfile.BadZipFile):
            continue
        if text:
            chunks.append(f"Source: {asset['name']}\n{text[:1200]}")
    return "\n\n".join(chunks)[:max_chars]


def _build_content_plan_from_documents(document_assets: list[dict]) -> dict:
    context = _read_document_context(document_assets, max_chars=12000)
    lines = _split_lines(context)
    headings = [
        line.strip("#: ")
        for line in lines
        if line.startswith("#") or line.endswith(":") or len(line.split()) <= 7
    ][:8]
    substantive = [
        line
        for line in lines
        if len(line.split()) >= 5 and not line.lower().startswith("source")
    ]
    key_points = substantive[:8]
    if not key_points:
        key_points = lines[:8]

    title = headings[0] if headings else (key_points[0][:72] if key_points else "Document-based video")
    audience = "People who need a concise visual explanation of the source material"
    objective = f"Turn {len(document_assets)} source document(s) into a clear, reviewable video script."
    structure = [
        "Open with the problem or purpose from the source material",
        "Group related points into a simple sequence",
        "Use uploaded images as visual evidence or examples",
        "End with the decision, takeaway, or action the viewer should remember",
    ]
    return {
        "title": title,
        "audience": audience,
        "objective": objective,
        "key_points": key_points,
        "suggested_structure": structure,
        "source_count": len(document_assets),
    }


def _format_content_plan(plan: dict) -> str:
    if not plan:
        return ""
    parts = [
        f"Title: {plan.get('title', '')}",
        f"Audience: {plan.get('audience', '')}",
        f"Objective: {plan.get('objective', '')}",
        "",
        "Key points:",
        *[f"- {point}" for point in plan.get("key_points", [])],
        "",
        "Suggested structure:",
        *[f"- {step}" for step in plan.get("suggested_structure", [])],
    ]
    return "\n".join(parts)


def _fetch_learn_page(url: str) -> dict:
    import re
    import requests

    if not url.strip():
        return {}
    response = requests.get(url.strip(), timeout=20)
    response.raise_for_status()
    html = response.text
    title_match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else url.strip()
    title = title.replace(" | Microsoft Learn", "")
    main_match = re.search(r"<main[^>]*>(.*?)</main>", html, flags=re.I | re.S)
    content = main_match.group(1) if main_match else html
    content = re.sub(r"<script.*?</script>|<style.*?</style>", " ", content, flags=re.I | re.S)
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"\s+", " ", content).strip()
    return {"title": title, "url": url.strip(), "text": content[:8000]}


def _scan_explainer_folder(folder_text: str) -> dict:
    doc_exts = {".txt", ".md", ".csv", ".log", ".docx", ".pptx", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml"}
    image_exts = {".png", ".jpg", ".jpeg", ".webp"}
    video_exts = {".mp4", ".mkv", ".webm", ".mov"}
    assets = {"documents": [], "images": [], "videos": []}
    for raw in folder_text.splitlines():
        folder = Path(raw.strip().strip('"'))
        if not folder.exists() or not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            item = {"name": path.name, "path": str(path)}
            if ext in image_exts:
                assets["images"].append(item)
            elif ext in video_exts:
                assets["videos"].append(item)
            elif ext in doc_exts:
                assets["documents"].append(item)
    return assets


def _build_technical_explainer_plan(
    *,
    topic: str,
    user_explanation: str,
    misunderstandings: str,
    feature_focus: str,
    audience: str,
    title_page: str,
    learn_source: dict,
    folder_assets: dict,
    series_mode: bool = False,
    max_parts: int = 4,
) -> dict:
    misunderstanding_lines = _split_lines(misunderstandings)
    if not misunderstanding_lines:
        misunderstanding_lines = [
            "People confuse the feature with a similar option",
            "People miss the decision rule for when to use it",
        ]
    source_points = _split_lines(learn_source.get("text", ""))[:6] if learn_source else []
    document_names = [item["name"] for item in folder_assets.get("documents", [])[:6]]
    image_names = [item["name"] for item in folder_assets.get("images", [])[:4]]
    video_names = [item["name"] for item in folder_assets.get("videos", [])[:3]]
    visual_strategy = "Animated mental model with cited source callouts"
    if video_names:
        visual_strategy = "Narrated explainer with inserted demo clip references"
    elif image_names:
        visual_strategy = "Screenshot-led walkthrough with animated callouts"
    elif "architecture" in topic.lower() or "orchestration" in topic.lower():
        visual_strategy = "Architecture diagram and decision-flow animation"

    content_signals = len(source_points) + len(document_names) + len(image_names) + len(video_names) + len(misunderstanding_lines)
    should_split = series_mode or content_signals > 10
    series_parts = []
    if should_split:
        part_count = max(2, min(max_parts, max(3, (content_signals + 3) // 4)))
        base_parts = [
            ("Foundation", "Set up the mental model, vocabulary, and why the concept matters."),
            ("Misunderstandings", "Correct the most common wrong assumptions before adding detail."),
            ("How it works", "Explain the mechanics, flow, or architecture in manageable steps."),
            ("Decision guidance", "Compare options and give rules for when to use each one."),
            ("Applied demo", "Use screenshots, examples, or existing demo clips to make it concrete."),
            ("Recap and next steps", "Tie the parts together and leave the viewer with a durable takeaway."),
        ]
        for idx, (name, goal) in enumerate(base_parts[:part_count], start=1):
            series_parts.append({
                "part": idx,
                "title": f"Part {idx}: {name}",
                "learning_goal": goal,
                "focus": misunderstanding_lines[idx - 1] if idx - 1 < len(misunderstanding_lines) else feature_focus.strip() or topic.strip(),
                "visual": ["mental model", "myth vs fact", "diagram", "decision flow", "demo clip", "recap"][idx - 1],
            })

    return {
        "title": title_page.strip() or topic.strip()[:80] or "Technical explainer",
        "topic": topic.strip(),
        "audience": audience.strip() or "Advisory and field teams",
        "user_explanation": user_explanation.strip(),
        "feature_focus": feature_focus.strip(),
        "misunderstandings": misunderstanding_lines,
        "learn_source": learn_source,
        "document_names": document_names,
        "image_names": image_names,
        "video_names": video_names,
        "source_points": source_points,
        "visual_strategy": visual_strategy,
        "series_mode": should_split,
        "series_parts": series_parts,
        "critique": [
            "Ground claims in Learn/local sources before rendering.",
            "Open with the misconception, not a feature list.",
            "Use one visual job per scene.",
            "End with a decision rule the viewer can reuse.",
            "If the source is large, split it into a series of parts that build understanding progressively.",
        ],
    }


def _format_technical_plan(plan: dict) -> str:
    if not plan:
        return ""
    source = plan.get("learn_source") or {}
    parts = [
        f"Title: {plan.get('title', '')}",
        f"Audience: {plan.get('audience', '')}",
        f"Feature focus: {plan.get('feature_focus', '')}",
        f"Visual strategy: {plan.get('visual_strategy', '')}",
        "",
        "User explanation:",
        plan.get("user_explanation", ""),
        "",
        "Misunderstandings to address:",
        *[f"- {item}" for item in plan.get("misunderstandings", [])],
    ]
    if source:
        parts.extend(["", "Primary Learn source:", f"- {source.get('title', '')}: {source.get('url', '')}"])
    if plan.get("document_names"):
        parts.extend(["", "Local documents:", *[f"- {name}" for name in plan["document_names"]]])
    if plan.get("image_names"):
        parts.extend(["", "Local images/screenshots:", *[f"- {name}" for name in plan["image_names"]]])
    if plan.get("video_names"):
        parts.extend(["", "Existing demo videos:", *[f"- {name}" for name in plan["video_names"]]])
    if plan.get("series_parts"):
        parts.extend(["", "Learning series:"])
        for part in plan["series_parts"]:
            parts.append(f"- {part['title']} — {part['learning_goal']} Focus: {part['focus']}")
    parts.extend(["", "Self-critique checklist:", *[f"- {item}" for item in plan.get("critique", [])]])
    return "\n".join(parts)


def _technical_scenes_from_plan(plan: dict) -> list[dict]:
    topic = plan.get("topic") or plan.get("title") or "this concept"
    audience = plan.get("audience", "the audience")
    misunderstandings = plan.get("misunderstandings", [])
    feature_focus = plan.get("feature_focus") or "the most important feature aspect"
    source_title = (plan.get("learn_source") or {}).get("title", "the source material")
    image_paths = [item["path"] for item in st.session_state.get("technical_folder_assets", {}).get("images", [])]
    if plan.get("series_parts"):
        scenes = [
            {
                "title": plan.get("title", topic),
                "layout": "Title card",
                "style": "Executive dark",
                "narration": f"This is a learning series for {audience}. Instead of compressing a large topic into one dense video, it splits {topic} into parts that build toward the full understanding.",
                "bullets": "Series overview\nProgressive learning path\nReviewable parts",
            },
            {
                "title": "Learning path",
                "layout": "Process",
                "style": "Coral energy",
                "narration": "The sequence starts with foundations, corrects misunderstandings early, then moves into mechanics, decision guidance, and applied examples.",
                "bullets": "\n".join(part["title"] for part in plan["series_parts"][:6]),
            },
        ]
        for part in plan["series_parts"]:
            scenes.append({
                "title": part["title"],
                "layout": "Spotlight",
                "style": "Berry premium",
                "narration": f"{part['title']} focuses on this learning goal: {part['learning_goal']} The key focus is {part['focus']}.",
                "bullets": f"Learning goal: {part['learning_goal']}\nFocus: {part['focus']}\nVisual: {part['visual']}",
            })
        scenes.append({
            "title": "How the parts fit together",
            "layout": "Checklist",
            "style": "Executive dark",
            "narration": f"By the end of the series, the viewer should understand {topic}, know what to compare it with, and have a decision rule they can apply in customer conversations.",
            "bullets": "Understand the concept\nAvoid the misunderstanding\nChoose the right option\nApply it in the field",
        })
        for scene, image_path in zip(scenes[2:], image_paths):
            scene["image_path"] = image_path
        return scenes

    scenes = [
        {
            "title": plan.get("title", topic),
            "layout": "Title card",
            "style": "Executive dark",
            "narration": f"This short explainer is for {audience}. It focuses on {feature_focus} and addresses the most common misunderstandings around {topic}.",
            "bullets": f"{feature_focus}\nGrounded in sources\nBuilt for understanding",
        },
        {
            "title": "The misconception",
            "layout": "Two-column",
            "style": "Coral energy",
            "narration": f"The first thing to fix is the mental model. A common misunderstanding is: {misunderstandings[0] if misunderstandings else 'people are using the wrong comparison point'}.",
            "bullets": "\n".join(misunderstandings[:3]),
        },
        {
            "title": "The right mental model",
            "layout": "Process",
            "style": "Berry premium",
            "narration": f"Think of {topic} as a decision pattern, not just a feature. Start with the goal, identify the constraint, then choose the Microsoft option that best matches the job.",
            "bullets": "Goal\nConstraint\nOption\nDecision",
        },
        {
            "title": "What the source says",
            "layout": "Spotlight",
            "style": "Clean light",
            "narration": f"The explanation is grounded in {source_title}. The video should cite the source and translate it into practical advisory guidance.",
            "bullets": "\n".join(plan.get("source_points", [])[:3]) or "Cited source\nPlain-language summary\nActionable takeaway",
        },
        {
            "title": "Decision rule",
            "layout": "Checklist",
            "style": "Executive dark",
            "narration": f"The takeaway is simple: use {feature_focus} when it solves the viewer's actual scenario, and compare it clearly against similar options before recommending it.",
            "bullets": "When to use it\nWhen not to use it\nWhat to compare\nWhat to do next",
        },
    ]
    for scene, image_path in zip(scenes[1:], image_paths):
        scene["image_path"] = image_path
    return scenes


def _image_assets() -> list[dict]:
    return [a for a in st.session_state.get("content_assets", []) if a.get("kind") == "images"]


def _video_assets() -> list[dict]:
    return [a for a in st.session_state.get("content_assets", []) if a.get("kind") == "videos"]


def _document_assets() -> list[dict]:
    return [a for a in st.session_state.get("content_assets", []) if a.get("kind") == "documents"]

st.set_page_config(
    page_title="CAT Video Tools",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4fc3f7, #ba68c8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .tool-card {
        background: #1e1e2e;
        border-radius: 12px;
        padding: 1.5rem;
        border: 1px solid #333;
        margin-bottom: 1rem;
    }
    .cat-hero {
        padding: 2.25rem 2.4rem;
        border-radius: 28px;
        background:
            radial-gradient(circle at top left, rgba(56, 189, 248, 0.34), transparent 34%),
            radial-gradient(circle at bottom right, rgba(168, 85, 247, 0.32), transparent 34%),
            linear-gradient(135deg, #0f172a 0%, #172554 52%, #312e81 100%);
        color: white;
        box-shadow: 0 24px 64px rgba(15, 23, 42, 0.22);
        margin-bottom: 1.5rem;
    }
    .cat-eyebrow {
        color: #bae6fd;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
        font-size: .78rem;
        margin-bottom: .65rem;
    }
    .cat-hero h1 {
        font-size: 3.2rem;
        line-height: 1.04;
        margin: 0 0 .8rem 0;
        letter-spacing: -0.05em;
    }
    .cat-hero p {
        font-size: 1.08rem;
        color: #dbeafe;
        max-width: 860px;
        margin-bottom: 1.15rem;
    }
    .cat-pill-row {
        display: flex;
        flex-wrap: wrap;
        gap: .6rem;
        margin-top: 1.1rem;
    }
    .cat-pill {
        border: 1px solid rgba(255,255,255,.22);
        background: rgba(255,255,255,.10);
        border-radius: 999px;
        padding: .46rem .78rem;
        color: #eff6ff;
        font-size: .88rem;
        backdrop-filter: blur(10px);
    }
    .section-kicker {
        color: #0ea5e9;
        font-weight: 800;
        letter-spacing: .08em;
        text-transform: uppercase;
        font-size: .76rem;
        margin-top: .6rem;
    }
    .landing-card {
        border: 1px solid #e5e7eb;
        border-radius: 20px;
        padding: 1.15rem;
        background: #ffffff;
        min-height: 190px;
        box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
    }
    .landing-card h3 {
        margin-top: 0;
        margin-bottom: .35rem;
        color: #111827;
    }
    .landing-card p {
        color: #4b5563;
        margin-bottom: .8rem;
    }
    .landing-card ul {
        padding-left: 1.1rem;
        color: #374151;
    }
    .demo-card {
        border: 1px solid #dbeafe;
        border-radius: 20px;
        padding: 1rem;
        background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
        box-shadow: 0 12px 28px rgba(30, 64, 175, 0.08);
        height: 100%;
    }
    .demo-card h4 {
        margin: 0 0 .35rem 0;
        color: #111827;
        font-size: 1.05rem;
    }
    .demo-meta {
        color: #64748b;
        font-size: .82rem;
        margin-bottom: .55rem;
    }
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #4fc3f7, #81c784);
    }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="main-header">🎬 CAT Video Tools</p>', unsafe_allow_html=True)
    st.caption("Power CAT Video Production Suite")
    st.divider()

    tool = st.radio(
        "Select Tool",
        ["🏠 Home", "✂️ Meeting Sanitizer", "🎞️ Clip Extractor", "🎥 Demo Video Creator", "🧠 Technical Explainer Studio", "🧪 Test Gallery"],
        index=0,
    )

    st.divider()
    st.caption("v1.0 • Built with Streamlit")
    st.caption("GitHub: [@KarimaKT](https://github.com/KarimaKT)")
    st.caption("[Repo](https://github.com/KarimaKT/cat-video-tools)")


# ── Home Page ────────────────────────────────────────────────────────────────
if tool == "🏠 Home":
    manifest = _load_demo_manifest()
    demos = manifest.get("demos", [])
    current_demos = sorted([
        demo for demo in demos
        if "better demo - generated" in str(demo.get("status", ""))
        and demo.get("front_page")
    ], key=_workflow_order_key)
    workflow_demos = {
        "sanitizer": _first_demo_for(current_demos, "sanitizer"),
        "clip extraction": _first_demo_for(current_demos, "clip extraction"),
        "creator": _first_demo_for(current_demos, "creator"),
        "technical explainer": _first_demo_for(current_demos, "technical explainer"),
    }
    evaluation_demos = [
        demo for demo in demos
        if "standalone learning series" in str(demo.get("status", ""))
    ][:5]

    st.markdown("""
    <div class="cat-hero">
        <div class="cat-eyebrow">Power CAT video production suite</div>
        <h1>Introducing CAT Video Tools</h1>
        <p>
            A local production app for turning meetings, recordings, scripts, source folders,
            Microsoft Learn pages, and technical topics into reviewable, publishable video assets.
        </p>
        <div class="cat-pill-row">
            <span class="cat-pill">Meeting sanitization</span>
            <span class="cat-pill">Publishable clips</span>
            <span class="cat-pill">Demo video creation</span>
            <span class="cat-pill">Technical teaching videos</span>
            <span class="cat-pill">Demo gallery</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    metric1, metric2, metric3, metric4 = st.columns(4)
    metric1.metric("Tools", "4", "one local suite")
    metric2.metric("Review gates", "2x", "script checks")
    metric3.metric("Demo videos", str(len([d for d in workflow_demos.values() if d])), "in workflows")
    metric4.metric("Course parts", str(len(evaluation_demos)), "evaluation series")

    st.markdown('<div class="section-kicker">Choose a workflow</div>', unsafe_allow_html=True)
    st.markdown("## Four production workflows")
    st.caption("Each workflow card includes the product promise, the generated video, and the caption in one place.")

    def render_workflow_video(kind: str) -> None:
        demo = workflow_demos.get(kind)
        if not demo:
            st.info("Demo not generated yet.")
            return
        media_path = _demo_media_path(demo)
        if media_path and media_path.exists():
            st.video(str(media_path))
        elif media_path:
            st.warning(f"Demo media missing: `{media_path}`")
        if demo.get("description"):
            st.caption(demo["description"])

    def render_workflow_card(title: str, body: str, bullets: list[str], kind: str) -> None:
        with st.container(border=True):
            st.markdown(f"### {title}")
            st.write(body)
            for bullet in bullets:
                st.markdown(f"- {bullet}")
            render_workflow_video(kind)

    card1, card2 = st.columns(2)
    with card1:
        render_workflow_card(
            "✂️ Meeting Sanitizer",
            "Prepare recorded meetings for safer sharing with review-first cuts, masking, and title/end cards.",
            [
                "Transcript-guided cuts and manual overrides",
                "Presenter preservation and non-presenter masking",
                "Frame verification before rendering",
            ],
            "sanitizer",
        )
    with card2:
        render_workflow_card(
            "🎞️ Clip Extractor",
            "Turn long recordings into intentional short clips with clean re-encoding and validated streams.",
            [
                "Manual ranges with editable titles/categories",
                "Normalized audio and FFprobe validation",
                "ZIP packaging for review and reuse",
            ],
            "clip extraction",
        )

    card3, card4 = st.columns(2)
    with card3:
        render_workflow_card(
            "🎥 Demo Video Creator",
            "Create short product demos and web walkthroughs from reviewed scripts, page steps, voice, and validation.",
            [
                "Structured script-to-demo workflow",
                "Raw walkthrough footage plus narrated assembly",
                "Neural narration and styled slides",
            ],
            "creator",
        )
    with card4:
        render_workflow_card(
            "🧠 Technical Explainer Studio",
            "Transform hard technical topics into source-grounded teaching videos with learning design before rendering.",
            [
                "User framing, misunderstandings, and feature focus",
                "Microsoft Learn pages, local folders, screenshots, demos",
                "Self-critique and editable storyboard",
            ],
            "technical explainer",
        )

    if evaluation_demos:
        st.divider()
        st.markdown('<div class="section-kicker">Learning series example</div>', unsafe_allow_html=True)
        st.markdown("## Evaluating Copilot Studio Agents")
        st.caption("A featured course-style output from Technical Explainer Studio, shown here as proof of the app's learning-video workflow.")
        tabs = st.tabs([f"Part {i + 1}" for i in range(len(evaluation_demos))])
        for tab, demo in zip(tabs, evaluation_demos):
            media_path = _demo_media_path(demo)
            with tab:
                st.markdown(f"### {demo.get('title', 'Evaluation video').replace('Standalone course video: ', '')}")
                if demo.get("description"):
                    st.write(demo["description"])
                if media_path and media_path.exists():
                    st.video(str(media_path))
                elif media_path:
                    st.warning(f"Series media missing: `{media_path}`")

    st.divider()
    st.markdown("### Built for review before publish")
    st.write(
        "Every workflow is designed to make decisions visible before rendering: "
        "scripts, clip ranges, speaker choices, masking, visuals, and generated outputs stay local and reviewable."
    )


# ── Meeting Sanitizer ────────────────────────────────────────────────────────
elif tool == "✂️ Meeting Sanitizer":
    st.markdown("## ✂️ Meeting Sanitizer")
    st.markdown("Upload your recording and transcript. I'll clean it up professionally.")

    with st.expander("ℹ️ What this tool does", expanded=False):
        st.markdown("""
        - **Analyzes** your transcript to find non-target speakers and admin chatter
        - **Detects** the video layout (side panel, participant tiles) automatically
        - **Cuts** disturbance zones entirely (interruptions + reactions like "shall we mute you?")
        - **Masks** non-target participant tiles with black overlays
        - **Enhances** audio: noise reduction + loudness normalization
        """)

    _skill_callout(
        "Start with a Clawpilot prep skill",
        "Use **`/meeting-sanitizer-plan`** before uploading when you want help turning rough recording notes, "
        "speaker names, transcript excerpts, or privacy concerns into keep-speaker guidance, candidate ranges, "
        "masking checks, and title/end-card text. Bring the reviewed plan back here before auditing or rendering.",
        """
/meeting-sanitizer-plan

Recording: [what this meeting/video is]
Keep speakers: [names to preserve]
Remove or mask: [people/sections/privacy concerns]
Known timestamps or transcript notes: [optional]
""",
    )

    st.divider()

    # File uploads
    col1, col2 = st.columns(2)
    with col1:
        video_file = st.file_uploader("📹 Upload Recording", type=["mp4", "mkv", "webm"],
                                       help="Teams or Zoom recording file")
    with col2:
        vtt_file = st.file_uploader("📝 Upload Transcript", type=["vtt", "srt"],
                                     help="VTT transcript (Teams auto-generates these)")

    # Speaker selection
    st.markdown("### Speakers to Keep")

    speakers_text = st.text_area(
        "Enter speaker names (one per line)",
        placeholder="Presenter One\nPresenter Two",
        help="Exact names as they appear in the transcript. Run 'Audit' first to see all detected names.",
        height=100,
    )

    # Advanced options
    with st.expander("⚙️ Advanced Options"):
        col1, col2, col3 = st.columns(3)
        with col1:
            crf = st.slider("Quality (CRF)", 18, 32, 22,
                           help="Lower = better quality, bigger file. 22 = high quality default.")
        with col2:
            audio_enhance = st.checkbox("Audio Enhancement", value=True,
                                       help="Noise reduction + loudness normalization")
        with col3:
            template = st.selectbox("Template", ["ai_webinar", "custom"],
                                   help="Preset disturbance detection patterns")
        col1, col2 = st.columns(2)
        with col1:
            conversation_aware_masking = st.checkbox(
                "Conversation-aware masking",
                value=True,
                help="Keep multiple presenter tiles only when the clean segment contains dialogue between approved presenters.",
            )
        with col2:
            preserve_presenter_names = st.checkbox(
                "Preserve approved presenter names",
                value=True,
                help="Do not blanket-mask presenter name bars when the remaining segment belongs to approved presenters.",
            )

        segments_text = st.text_area(
            "Time Segments (optional)",
            placeholder="6:09 - 66:57  # Main content\n71:11 - 71:31  # Closing",
            help="Leave blank to process entire video. Format: start - end (MM:SS or H:MM:SS)",
            height=80,
        )

        additional_notes = st.text_area(
            "Additional Instructions (optional)",
            placeholder="E.g., 'End after the presenter says: and that is why the integration matters'",
            height=60,
        )
        verify_time_text = st.text_input(
            "Verify frame source time",
            placeholder="6:09",
            help="Used by Verify Frame to extract one masked frame before rendering.",
        )

    with st.expander("Title and ending cards"):
        st.caption("Optional publish-ready cards are added with the same validated media pipeline as the rest of the app.")
        title_card_text = st.text_input("Title card text", placeholder="Technical Demo: Agent Orchestration Patterns")
        title_card_subtitle = st.text_input("Title card subtitle", placeholder="Presenter Name | Team")
        ending_card_text = st.text_input("Ending card text", placeholder="Thank you | Learn more in the linked resources")

    st.divider()

    # Actions
    col1, col2, col3 = st.columns(3)

    with col1:
        audit_btn = st.button("🔍 Audit Only", use_container_width=True,
                             help="Analyze and show edit plan without rendering")
    with col2:
        render_btn = st.button("▶️ Render Video", type="primary", use_container_width=True,
                              help="Full analysis + render")
    with col3:
        verify_btn = st.button("🖼️ Verify Frame", use_container_width=True,
                              help="Extract a masked frame for visual QA")

    # Processing logic
    if (audit_btn or render_btn or verify_btn) and video_file and vtt_file and speakers_text.strip():
        # Save uploaded files to temp dir
        work_dir = Path(tempfile.mkdtemp(prefix="sanitizer_"))
        video_path = str(work_dir / "input.mp4")
        vtt_path = str(work_dir / "transcript.vtt")
        output_path = str(work_dir / "output.mp4")
        raw_output_path = str(work_dir / "output_raw.mp4")

        with open(video_path, "wb") as f:
            f.write(video_file.read())
        with open(vtt_path, "wb") as f:
            f.write(vtt_file.read())

        keep_speakers = [s.strip() for s in speakers_text.strip().split("\n") if s.strip()]

        # Parse segments if provided
        segments = None
        if segments_text.strip():
            segments = _parse_segments(segments_text)

        with st.spinner("Analyzing recording..."):
            try:
                from meeting_editor import MeetingEditor

                editor = MeetingEditor(
                    video_path=video_path,
                    vtt_path=vtt_path,
                    keep_speakers=keep_speakers,
                    segments=segments,
                    conversation_aware_masking=conversation_aware_masking,
                    preserve_presenter_names=preserve_presenter_names,
                )
                editor.analyze()

                # Show audit results
                st.markdown("### 📋 Audit Report")

                # Speakers found
                st.markdown("**Speakers detected:**")
                for name, dur in sorted(editor.all_speakers.items(), key=lambda x: -x[1]):
                    tag = "✅ KEEP" if name in editor.keep_speakers else "❌ REMOVE"
                    st.text(f"  {tag}  {name} ({dur/60:.1f} min)")

                # Disturbances
                if editor.disturbances:
                    st.markdown(f"**Disturbance zones found: {len(editor.disturbances)}**")
                    for d in sorted(editor.disturbances, key=lambda x: x.start):
                        dur = d.end - d.start
                        st.text(f"  ✂️ CUT {_fmt_time(d.start)} → {_fmt_time(d.end)} ({dur:.1f}s) — {d.reason}")

                # Clean segments
                st.markdown(f"**Output: {len(editor.clean_segments)} segments, "
                           f"{sum(e-s for s,e in editor.clean_segments)/60:.1f} min**")

                with st.expander("Transcript preview after planned cuts", expanded=False):
                    st.caption("Use this to catch missing tail phrases or incomplete final sentences before rendering.")
                    st.text(editor.planned_transcript_text())

                # Verify one masked frame if requested
                if verify_btn:
                    if not verify_time_text.strip():
                        st.warning("Enter a source timestamp to verify, such as 6:09.")
                    else:
                        verify_time = _parse_time(verify_time_text)
                        if verify_time is None:
                            st.warning("Could not parse the verify timestamp.")
                        else:
                            frame_path = editor.verify_frame(verify_time)
                            st.success(f"Verification frame extracted at {_fmt_time(verify_time)}.")
                            st.image(frame_path, caption="Masked frame preview", use_container_width=True)

                # Render if requested
                if render_btn:
                    st.divider()
                    progress = st.progress(0, text="Rendering...")

                    rendered = editor.process(raw_output_path, crf=crf, audio_enhance=audio_enhance)
                    if rendered:
                        _add_title_and_end_cards(
                            source_video=raw_output_path,
                            output_video=output_path,
                            title_text=title_card_text,
                            subtitle_text=title_card_subtitle,
                            end_text=ending_card_text,
                        )
                    progress.progress(100, text="Complete!")

                    if os.path.exists(output_path):
                        st.success("✅ Video rendered successfully!")
                        with open(output_path, "rb") as f:
                            st.download_button(
                                "⬇️ Download Sanitized Video",
                                f.read(),
                                file_name="sanitized_output.mp4",
                                mime="video/mp4",
                                type="primary",
                            )

            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                # Cleanup happens on next run or session end
                pass

    elif (audit_btn or render_btn or verify_btn):
        st.warning("Please upload both a video and transcript, and enter at least one speaker name.")


# ── Clip Extractor ───────────────────────────────────────────────────────────
elif tool == "🎞️ Clip Extractor":
    st.markdown("## 🎞️ Clip Extractor")
    st.markdown("Create publishable short clips from manual ranges, with validated audio/video output.")

    with st.expander("ℹ️ What this tool does", expanded=False):
        st.markdown("""
        - Uses precise start/end ranges you provide
        - Re-encodes clips intentionally instead of stream-copying fragile cuts
        - Normalizes audio and validates every output with FFprobe
        - Packages multiple clips into a ZIP for download
        """)

    _skill_callout(
        "Start with a Clawpilot clip-planning skill",
        "Use **`/clip-extractor-plan`** when you have a webinar, transcript notes, or rough moments but need "
        "viewer-facing clip titles, categories, and paste-ready ranges. Bring the reviewed clip plan back here, "
        "then render only the clips you approve.",
        """
/clip-extractor-plan

Source: [recording or webinar]
Audience: [who the clips are for]
Moments or transcript notes: [timestamps if known]
Goal: [what the clip set should help viewers understand]
""",
    )

    video_file = st.file_uploader("📹 Upload Source Recording", type=["mp4", "mkv", "webm"], key="clip_video")

    clips_text = st.text_area(
        "Clip ranges",
        placeholder=(
            "6:09 - 7:17 | Agents Are Not Apps | AI agents\n"
            "22:51 - 26:20 | Natural Language to Query | Structured data"
        ),
        help="One clip per line: start - end | title | optional category. Times can be MM:SS or H:MM:SS.",
        height=140,
    )

    col1, col2 = st.columns(2)
    with col1:
        clip_crf = st.slider("Clip Quality (CRF)", 18, 32, 20, help="Lower = better quality, bigger file.")
    with col2:
        clip_audio_enhance = st.checkbox("Normalize/enhance audio", value=True)

    if st.button("📋 Build editable clip plan", use_container_width=True):
        clips = _parse_clip_specs(clips_text)
        if not clips:
            st.warning("Add at least one valid clip range.")
        else:
            st.session_state.clip_plan = [
                {
                    "include": True,
                    "start": _fmt_time(clip.start),
                    "end": _fmt_time(clip.end),
                    "title": clip.title,
                    "category": clip.category,
                }
                for clip in clips
            ]
            st.success(f"Created editable plan for {len(clips)} clip(s). Review before rendering.")

    if "clip_plan" in st.session_state and st.session_state.clip_plan:
        st.markdown("### Review clip plan before rendering")
        st.caption("Edit ranges, titles, categories, or exclude weak clips before the app renders anything.")
        for i, item in enumerate(st.session_state.clip_plan):
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([0.6, 1, 1, 2])
                with col1:
                    st.session_state.clip_plan[i]["include"] = st.checkbox("Use", value=item.get("include", True), key=f"clip_use_{i}")
                with col2:
                    st.session_state.clip_plan[i]["start"] = st.text_input("Start", item.get("start", ""), key=f"clip_start_{i}")
                with col3:
                    st.session_state.clip_plan[i]["end"] = st.text_input("End", item.get("end", ""), key=f"clip_end_{i}")
                with col4:
                    st.session_state.clip_plan[i]["title"] = st.text_input("Title", item.get("title", ""), key=f"clip_title_{i}")
                st.session_state.clip_plan[i]["category"] = st.text_input("Category", item.get("category", ""), key=f"clip_cat_{i}")

    approved_clips = st.checkbox("I reviewed the clip plan. Render selected clips.", key="clip_plan_approved")
    if st.button("🎬 Render reviewed clips", type="primary", use_container_width=True, disabled=not approved_clips):
        plan = st.session_state.get("clip_plan", [])
        selected = [item for item in plan if item.get("include")]
        if not video_file:
            st.warning("Upload a source recording first.")
        elif not selected:
            st.warning("Select at least one clip to render.")
        else:
            from clip_extractor import ClipSpec, safe_clip_id
            clips = []
            for item in selected:
                start = _parse_time(item.get("start", ""))
                end = _parse_time(item.get("end", ""))
                if start is None or end is None or end <= start:
                    st.warning(f"Skipping invalid clip range: {item.get('title')}")
                    continue
                title = item.get("title", "Clip")
                clips.append(ClipSpec(
                    id=safe_clip_id(title),
                    title=title,
                    start=start,
                    end=end,
                    category=item.get("category", ""),
                    manual=True,
                ))

            if not clips:
                st.warning("No valid clips remain after review.")
            else:
                work_dir = Path(tempfile.mkdtemp(prefix="clip_extractor_"))
                video_path = work_dir / "source.mp4"
                output_dir = work_dir / "clips"
                zip_path = work_dir / "clips.zip"

                with open(video_path, "wb") as f:
                    f.write(video_file.read())

                with st.spinner(f"Extracting {len(clips)} reviewed clip(s)..."):
                    try:
                        from clip_extractor import extract_clips

                        results = extract_clips(
                            video_path=video_path,
                            clips=clips,
                            output_dir=output_dir,
                            crf=clip_crf,
                            audio_enhance=clip_audio_enhance,
                        )

                        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                            for result in results:
                                path = Path(result["output_path"])
                                zf.write(path, arcname=path.name)

                        st.success(f"✅ Extracted {len(results)} reviewed clip(s).")
                        for result in results:
                            clip = result["clip"]
                            summary = result["summary"]
                            st.markdown(f"**{clip.title}** — {summary['duration']:.1f}s · {summary['video_streams']} video / {summary['audio_streams']} audio stream")
                            st.video(result["output_path"])

                        with open(zip_path, "rb") as f:
                            st.download_button(
                                "⬇️ Download Clips ZIP",
                                f.read(),
                                file_name="clips.zip",
                                mime="application/zip",
                                type="primary",
                            )
                    except Exception as e:
                        st.error(f"Error: {e}")


# ── Demo Video Creator ───────────────────────────────────────────────────────
elif tool == "🎥 Demo Video Creator":
    st.markdown("## 🎥 Demo Video Creator")
    st.markdown("Create a short product demo, app walkthrough, or narrated web tour with a reviewable script before rendering.")

    with st.expander("ℹ️ What this tool does", expanded=False):
        st.markdown("""
        - Drafts short demo videos from a brief, or lets you write/upload one.
        - Creates web walkthroughs from a URL, timed screen sequence, and narration.
        - Gives you agency over title, narration, bullets, scene order, style, voice, and speed.
        - Generates narrated slides with motion and validates the final media output.
        - Keeps a script YAML you can inspect, edit, reuse, and archive.
        """)

    st.info(
        "**How this differs from Technical Explainer Studio:** Demo Video Creator is for showing an app, page, workflow, or feature quickly. "
        "Technical Explainer Studio is for deeper teaching: it researches sources, clarifies misunderstandings, designs a learning arc, and then renders."
    )

    st.divider()

    if "scenes" not in st.session_state:
        st.session_state.scenes = [{"title": "", "narration": "", "bullets": "", "layout": "Title card", "style": "Executive dark"}]
    if "creator_title" not in st.session_state:
        st.session_state.creator_title = "My Demo Video"
    if "creator_voice" not in st.session_state:
        st.session_state.creator_voice = "en-US-AriaNeural (Female)"
    if "creator_voice_rate" not in st.session_state:
        st.session_state.creator_voice_rate = "+5%"
    if "content_assets" not in st.session_state:
        st.session_state.content_assets = []

    input_method = st.radio(
        "What do you want to do first?",
        ["🌐 Create web walkthrough", "🪄 Draft from brief", "✍️ Review/edit scenes", "📄 Upload YAML script"],
        horizontal=True,
    )

    with st.expander("Brand, images, and source documents", expanded=True):
        st.caption("Drop in a title slide/PPT template, image assets, or source documents. Images can be assigned to scenes; documents are converted into a content plan before drafting scenes.")
        col1, col2 = st.columns(2)
        with col1:
            brand_upload = st.file_uploader(
                "Title slide or PPT template",
                type=["pptx", "png", "jpg", "jpeg"],
                key="brand_upload",
                help="Use a PPTX first slide, PNG, or JPG as a branded opener/title card.",
            )
            brand_asset = _save_brand_asset(brand_upload)
            if brand_asset:
                st.success(f"Brand asset ready: {brand_asset['name']}")
                if brand_asset.get("title_image"):
                    st.image(brand_asset["title_image"], caption="Title slide preview", use_container_width=True)
                elif brand_asset["type"] == "pptx":
                    st.warning("PPTX was saved, but PowerPoint could not export the first slide preview on this machine.")
        with col2:
            image_uploads = st.file_uploader("Images to use in the video", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
            video_uploads = st.file_uploader("Video clips to include", type=["mp4", "mkv", "webm", "mov"], accept_multiple_files=True)
            doc_uploads = st.file_uploader("Documents to use for content", type=["txt", "md", "csv", "log", "docx", "pptx"], accept_multiple_files=True)
            folder_text = st.text_area(
                "Or paste local folder paths, one per line",
                placeholder="C:\\path\\to\\screenshots\nC:\\path\\to\\source-docs",
                height=70,
            )
            if st.button("📥 Add assets to project"):
                added = []
                added.extend(_save_asset_uploads(image_uploads, "images"))
                added.extend(_save_asset_uploads(video_uploads, "videos"))
                added.extend(_save_asset_uploads(doc_uploads, "documents"))
                added.extend(_scan_asset_folders(folder_text))
                existing = {a["path"] for a in st.session_state.content_assets}
                st.session_state.content_assets.extend([a for a in added if a["path"] not in existing])
                st.success(f"Added {len([a for a in added if a['path'] not in existing])} new asset(s).")

        if st.session_state.content_assets:
            image_count = len(_image_assets())
            video_count = len(_video_assets())
            doc_count = len(_document_assets())
            st.caption(f"Current asset library: {image_count} image(s), {video_count} video clip(s), {doc_count} document(s).")
            if doc_count:
                if st.button("🧭 Build content plan from documents"):
                    st.session_state.content_plan = _build_content_plan_from_documents(_document_assets())
                    st.success("Content plan created from source documents. Review it below, then draft scenes from the plan.")
                if st.session_state.get("content_plan"):
                    with st.expander("Document-based content plan", expanded=True):
                        st.code(_format_content_plan(st.session_state.content_plan), language="markdown")
            with st.expander("Show asset list", expanded=False):
                for asset in st.session_state.content_assets:
                    st.code(f"{asset['kind']}: {asset['path']}")

    if input_method == "🌐 Create web walkthrough":
        st.markdown("### Create a narrated web walkthrough")
        st.caption("Use this for product tours and portal walkthroughs. Keep each screen beat to four seconds or less so the viewer always sees motion.")

        col1, col2 = st.columns([1.2, 1])
        with col1:
            walkthrough_url = st.text_input("Web page to show", value="http://localhost:8601")
            walkthrough_title = st.text_input("Walkthrough title", value="CAT Video Tools Portal Walkthrough")
        with col2:
            walkthrough_voice = st.selectbox("Narration voice", [
                "en-US-AriaNeural (Female)",
                "en-US-JennyNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-BrianNeural (Male)",
                "en-GB-SoniaNeural (Female, UK)",
            ], key="walkthrough_voice")
            walkthrough_rate = st.select_slider(
                "Narration speed",
                options=["+0%", "+5%", "+10%", "+15%", "+20%"],
                value="+10%",
                key="walkthrough_rate",
            )
            max_screen_seconds = st.slider(
                "Max seconds per screen",
                min_value=2.0,
                max_value=4.0,
                value=4.0,
                step=0.5,
                help="Each captured screen is capped here before moving to the next screen or section.",
            )

        default_steps = _format_walkthrough_steps(_default_web_walkthrough_steps(walkthrough_url))
        walkthrough_steps_text = st.text_area(
            "Sequence: screen label | action | narration",
            value=st.session_state.get("walkthrough_steps_text", default_steps),
            height=260,
            help="Actions supported: goto, wait, scroll:0.35, scroll:900, click:Visible text. Keep narration short for each screen.",
        )
        st.session_state.walkthrough_steps_text = walkthrough_steps_text

        steps = _parse_walkthrough_steps(walkthrough_steps_text)
        st.markdown("#### Preview")
        if not steps:
            st.warning("Add at least one valid step using: label | action | narration")
        else:
            for idx, step in enumerate(steps, start=1):
                st.markdown(f"**{idx}. {step['label']}** — `{step['action']}`")
                st.caption(step["narration"])

        plan_text = _walkthrough_plan_yaml(
            walkthrough_title,
            walkthrough_url,
            max_screen_seconds,
            walkthrough_voice,
            walkthrough_rate,
            steps,
        )
        with st.expander("Walkthrough YAML preview", expanded=False):
            st.code(plan_text, language="yaml")
        st.download_button("⬇️ Download walkthrough plan", plan_text, file_name="web_walkthrough.yaml", mime="text/yaml")

        approved_walkthrough = st.checkbox("I reviewed the web page, sequence, timings, and narration. Generate this walkthrough.")
        if st.button("▶️ Generate narrated walkthrough", type="primary", disabled=not approved_walkthrough):
            if not walkthrough_url.strip():
                st.warning("Enter the web page to show.")
            elif not steps:
                st.warning("Add at least one valid walkthrough step.")
            else:
                work_dir = Path(tempfile.mkdtemp(prefix="web_walkthrough_"))
                output_path = work_dir / "web_walkthrough.mp4"
                with st.spinner("Capturing screens and generating narrated walkthrough..."):
                    try:
                        from web_walkthrough import capture_web_walkthrough

                        result = capture_web_walkthrough(
                            url=walkthrough_url.strip(),
                            steps=steps,
                            output_dir=work_dir,
                            output_path=output_path,
                            title=walkthrough_title.strip() or "Web walkthrough",
                            voice=walkthrough_voice.split(" (")[0],
                            voice_rate=walkthrough_rate,
                            max_screen_seconds=max_screen_seconds,
                        )
                        st.success("✅ Narrated web walkthrough generated.")
                        st.video(result["video"])
                        st.caption(f"Duration: {result['summary']['duration']:.1f}s · Screens: {len(result['screenshots'])}")
                        walkthrough_asset = {
                            "name": Path(result["video"]).name,
                            "path": result["video"],
                            "kind": "videos",
                        }
                        existing = {a["path"] for a in st.session_state.content_assets}
                        if walkthrough_asset["path"] not in existing:
                            st.session_state.content_assets.append(walkthrough_asset)
                        if st.button("➕ Add this walkthrough as a scene", use_container_width=True):
                            st.session_state.scenes.append({
                                "title": "Live walkthrough",
                                "narration": "",
                                "bullets": "",
                                "layout": "Embedded video",
                                "style": "Executive dark",
                                "image_path": "",
                                "video_path": result["video"],
                                "visual": "video",
                            })
                            st.success("Walkthrough added to Review/edit scenes. Add intro and closing slides around it before rendering.")
                        with open(result["video"], "rb") as f:
                            st.download_button(
                                "⬇️ Download walkthrough video",
                                f.read(),
                                file_name="web_walkthrough.mp4",
                                mime="video/mp4",
                                type="primary",
                            )
                        with open(result["plan"], "rb") as f:
                            st.download_button(
                                "⬇️ Download captured plan",
                                f.read(),
                                file_name="web_walkthrough.yaml",
                                mime="text/yaml",
                            )
                    except Exception as e:
                        st.error(f"Error: {e}")

    elif input_method == "🪄 Draft from brief":
        st.markdown("### Generate an editable first draft")
        st.caption("Use this when you want a short demo script, but you still want to approve and edit before rendering.")

        col1, col2 = st.columns(2)
        with col1:
            default_plan = st.session_state.get("content_plan", {})
            topic = st.text_area(
                "What should the demo show?",
                placeholder="Show how human review happens before generating publishable video clips",
                value=default_plan.get("title", ""),
                height=120,
            )
            duration = st.select_slider(
                "Target Duration",
                options=["30 seconds", "60 seconds", "90 seconds", "2 minutes", "3 minutes", "5 minutes"],
                value="90 seconds",
            )
        with col2:
            audience = st.text_input(
                "Target Audience",
                value=st.session_state.get("content_plan", {}).get("audience", ""),
                placeholder="Field sellers, makers, customer engineers...",
            )
            key_points = st.text_area(
                "Demo plan / key points to cover",
                placeholder="- Start with a draft\n- Review and edit scenes\n- Generate only after approval\n- Validate the media output",
                value="\n".join(f"- {point}" for point in st.session_state.get("content_plan", {}).get("key_points", [])),
                height=120,
            )
            draft_voice = st.selectbox("Preferred Voice", [
                "en-US-AriaNeural (Female)",
                "en-US-JennyNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-BrianNeural (Male)",
                "en-GB-SoniaNeural (Female, UK)",
            ])

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🪄 Draft editable script", type="primary", use_container_width=True):
                if not topic.strip():
                    st.warning("Describe what the video should explain first.")
                else:
                    st.session_state.creator_title = topic.strip()[:80]
                    st.session_state.creator_voice = draft_voice
                    st.session_state.scenes = _draft_video_scenes(topic, audience, key_points, duration)
                    images = _image_assets()
                    for idx, scene in enumerate(st.session_state.scenes):
                        if idx < len(images):
                            scene["image_path"] = images[idx]["path"]
                            scene["visual"] = "image"
                            scene["layout"] = "Image spotlight"
                    st.success("Draft created. Switch to Review/edit scenes to adjust it before rendering.")
        with col2:
            st.info("Critical reviewer rule: do not render until the script, scene count, voice, and visual style have been reviewed.")

        if st.session_state.scenes:
            st.markdown("### Current draft preview")
            for i, scene in enumerate(st.session_state.scenes, start=1):
                st.markdown(f"**{i}. {scene.get('title', 'Untitled')}** — {scene.get('layout', 'Scene')} · {scene.get('style', 'Style')}")
                st.caption(scene.get("narration", "")[:220])

    elif input_method == "📄 Upload YAML script":
        st.markdown("### Upload an existing YAML script")
        st.caption("Drop a Video Creator YAML file here when you already have a reviewed script and want to render it directly.")

        sample_yaml = _sample_video_script_yaml()
        with st.container(border=True):
            st.markdown("#### Sample format")
            st.write("Download this sample when you need the expected fields for slides, narration, and embedded video or walkthrough scenes.")
            st.download_button(
                "⬇️ Download sample YAML",
                sample_yaml,
                file_name="sample_demo_video_script.yaml",
                mime="text/yaml",
                use_container_width=True,
            )
            with st.expander("Preview sample YAML", expanded=False):
                st.code(sample_yaml, language="yaml")

        _skill_callout(
            "Start from a Clawpilot skill",
            "If you only have a topic or rough scenario, use **`/demo-video-draft`** in Clawpilot first. "
            "Tell the skill your topic, audience, and what the viewer should understand. It will generate "
            "a Demo Video Creator YAML draft with placeholder screenshot or walkthrough paths.",
            """
/demo-video-draft

Topic: [your product, app, feature, or workflow]
Audience: [who will watch this demo]
Scenario: [why this matters and what the viewer should understand]

Then replace placeholder media paths, save the YAML, and upload it here.
""",
        )

        with st.container(border=True):
            st.markdown("#### 1. Choose YAML file")
            script_file = st.file_uploader(
                "Upload `.yaml` or `.yml` script",
                type=["yaml", "yml"],
                key="creator_yaml_upload",
                help="This should be a CAT Video Tools video script with title, voice, and scenes.",
            )

        if script_file:
            st.success(f"Ready to render: {script_file.name}")
            work_dir = Path(tempfile.mkdtemp(prefix="creator_"))
            script_path = str(work_dir / "script.yaml")
            output_path = str(work_dir / "output.mp4")

            with open(script_path, "wb") as f:
                f.write(script_file.read())

            st.info("Uploaded scripts render directly. Use Review/edit scenes when you want inline editing before render.")
            st.markdown("#### 2. Generate video")
            if st.button("▶️ Generate uploaded YAML script", type="primary", use_container_width=True):
                with st.spinner("Generating video..."):
                    try:
                        from video_creator import VideoCreator
                        creator = VideoCreator(script_path)
                        creator.generate(output_path)

                        if os.path.exists(output_path):
                            st.success("✅ Video generated!")
                            st.video(output_path)
                            with open(output_path, "rb") as f:
                                st.download_button(
                                    "⬇️ Download Video",
                                    f.read(),
                                    file_name="generated_video.mp4",
                                    mime="video/mp4",
                                    type="primary",
                                )
                    except Exception as e:
                        st.error(f"Error: {e}")
        else:
            st.warning("Upload a YAML script above to enable generation.")

    elif input_method == "✍️ Review/edit scenes":
        st.markdown("### 1. Video settings")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.session_state.creator_title = st.text_input("Video Title", st.session_state.creator_title)
        with col2:
            st.session_state.creator_voice = st.selectbox("Voice", [
                "en-US-AriaNeural (Female)",
                "en-US-JennyNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-BrianNeural (Male)",
                "en-GB-SoniaNeural (Female, UK)",
            ], index=[
                "en-US-AriaNeural (Female)",
                "en-US-JennyNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-BrianNeural (Male)",
                "en-GB-SoniaNeural (Female, UK)",
            ].index(st.session_state.creator_voice) if st.session_state.creator_voice in [
                "en-US-AriaNeural (Female)",
                "en-US-JennyNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-BrianNeural (Male)",
                "en-GB-SoniaNeural (Female, UK)",
            ] else 0)
        with col3:
            st.session_state.creator_voice_rate = st.select_slider(
                "Speed",
                options=["-20%", "-10%", "+0%", "+5%", "+10%", "+15%", "+20%"],
                value=st.session_state.creator_voice_rate,
            )

        st.markdown("### 2. Review and edit scenes")
        st.caption("Every generated or manual scene is editable before rendering. Remove weak scenes, add missing ones, and choose a visual style.")

        remove_index = None
        for i, scene in enumerate(st.session_state.scenes):
            with st.container(border=True):
                header_col, remove_col = st.columns([5, 1])
                with header_col:
                    st.markdown(f"#### Scene {i + 1}")
                with remove_col:
                    if len(st.session_state.scenes) > 1 and st.button("Remove", key=f"remove_scene_{i}"):
                        remove_index = i

                col1, col2, col3 = st.columns([1.2, 1, 1])
                with col1:
                    st.session_state.scenes[i]["title"] = st.text_input(
                        "Title", scene.get("title", ""), key=f"title_{i}")
                with col2:
                    layouts = ["Title card", "Two-column", "Process", "Checklist", "Spotlight", "Image spotlight", "Embedded video"]
                    st.session_state.scenes[i]["layout"] = st.selectbox(
                        "Layout", layouts,
                        index=layouts.index(scene.get("layout", "Title card")) if scene.get("layout", "Title card") in layouts else 0,
                        key=f"layout_{i}",
                    )
                with col3:
                    st.session_state.scenes[i]["style"] = st.selectbox(
                        "Visual style", ["Executive dark", "Coral energy", "Berry premium", "Clean light"],
                        index=["Executive dark", "Coral energy", "Berry premium", "Clean light"].index(scene.get("style", "Executive dark"))
                        if scene.get("style", "Executive dark") in ["Executive dark", "Coral energy", "Berry premium", "Clean light"] else 0,
                        key=f"style_{i}",
                    )

                image_options = ["No image"] + [asset["path"] for asset in _image_assets()]
                current_image = scene.get("image_path") if scene.get("image_path") in image_options else "No image"
                selected_image = st.selectbox(
                    "Scene image",
                    image_options,
                    index=image_options.index(current_image),
                    key=f"image_{i}",
                    help="Use uploaded images or images discovered from pasted folders.",
                )
                if selected_image != "No image":
                    st.image(selected_image, caption="Selected scene image", use_container_width=True)

                video_options = ["No video"] + [asset["path"] for asset in _video_assets()]
                current_video = scene.get("video_path") if scene.get("video_path") in video_options else "No video"
                selected_video = st.selectbox(
                    "Scene video / walkthrough clip",
                    video_options,
                    index=video_options.index(current_video),
                    key=f"video_{i}",
                    help="Use a generated web walkthrough, uploaded MP4, or video discovered from a pasted folder.",
                )
                st.session_state.scenes[i]["image_path"] = "" if selected_image == "No image" else selected_image
                st.session_state.scenes[i]["video_path"] = "" if selected_video == "No video" else selected_video
                if selected_video != "No video":
                    st.session_state.scenes[i]["visual"] = "video"
                    st.video(selected_video)
                    st.caption("Video scenes keep the clip audio by default. Leave narration blank unless you want a voiceover mixed over the clip.")
                elif selected_image != "No image":
                    st.session_state.scenes[i]["visual"] = "image"
                else:
                    st.session_state.scenes[i]["visual"] = "slide"

                col1, col2 = st.columns([1, 2])
                with col1:
                    st.session_state.scenes[i]["bullets"] = st.text_area(
                        "Bullet points (one per line)", scene.get("bullets", ""),
                        key=f"bullets_{i}", height=100)
                with col2:
                    st.session_state.scenes[i]["narration"] = st.text_area(
                        "Narration", scene.get("narration", ""),
                        key=f"narr_{i}", height=140,
                        placeholder="What the narrator says during this scene...")

        if remove_index is not None:
            st.session_state.scenes.pop(remove_index)
            st.rerun()

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("➕ Add blank scene", use_container_width=True):
                st.session_state.scenes.append({"title": "", "narration": "", "bullets": "", "layout": "Spotlight", "style": "Executive dark", "image_path": "", "video_path": "", "visual": "slide"})
                st.rerun()
        with col2:
            if st.button("📋 Duplicate last scene", use_container_width=True):
                st.session_state.scenes.append(dict(st.session_state.scenes[-1]))
                st.rerun()
        with col3:
            if st.button("🧹 Clear empty scenes", use_container_width=True):
                st.session_state.scenes = [s for s in st.session_state.scenes if s.get("narration") or s.get("title") or s.get("video_path")] or [{"title": "", "narration": "", "bullets": "", "layout": "Title card", "style": "Executive dark", "video_path": ""}]
                st.rerun()

        st.markdown("### 3. Review script before generation")
        script_text = _script_yaml(
            st.session_state.creator_title,
            st.session_state.creator_voice,
            st.session_state.creator_voice_rate,
            st.session_state.scenes,
        )
        with st.expander("Script YAML preview", expanded=False):
            st.code(script_text, language="yaml")
        st.download_button("⬇️ Download script YAML", script_text, file_name="video_script.yaml", mime="text/yaml")

        st.divider()
        approved = st.checkbox("I reviewed the script, scene order, voice, and visual style. Generate this version.")
        if st.button("▶️ Generate reviewed video", type="primary", disabled=not approved):
            scenes_with_content = [s for s in st.session_state.scenes if s.get("narration") or s.get("video_path")]
            if not scenes_with_content:
                st.warning("Add narration or a video/walkthrough clip to at least one scene.")
            else:
                work_dir = Path(tempfile.mkdtemp(prefix="creator_"))
                output_path = str(work_dir / "output.mp4")

                with st.spinner("Generating reviewed video..."):
                    try:
                        from video_creator import VideoCreator

                        script = _build_video_script(
                            st.session_state.creator_title,
                            st.session_state.creator_voice,
                            st.session_state.creator_voice_rate,
                            scenes_with_content,
                        )
                        _apply_brand_title_scene(script, st.session_state.creator_title, st.session_state.get("brand_asset"))
                        creator = VideoCreator(script=script)
                        creator.generate(output_path)

                        if os.path.exists(output_path):
                            st.success("✅ Reviewed video generated.")
                            st.video(output_path)
                            with open(output_path, "rb") as f:
                                st.download_button(
                                    "⬇️ Download Video",
                                    f.read(),
                                    file_name="reviewed_video.mp4",
                                    mime="video/mp4",
                                    type="primary",
                                )
                    except Exception as e:
                        st.error(f"Error: {e}")


# ── Technical Explainer Studio ───────────────────────────────────────────────
elif tool == "🧠 Technical Explainer Studio":
    st.markdown("## 🧠 Technical Explainer Studio")
    st.markdown(
        "Plan and generate a short explainer for a hard technical concept. "
        "The workflow starts with your intent and misunderstandings, then grounds the storyboard in Learn docs, local folders, screenshots, or existing demo assets."
    )

    _skill_callout(
        "Start with the technical learning skill",
        "Use **`/technical-learning-video`** when you want Clawpilot to help shape the topic, audience, "
        "misunderstandings, sources, and learning arc before you fill in this studio. Bring the resulting "
        "topic brief, source notes, or storyboard back here for rendering.",
        """
/technical-learning-video

Topic: [technical concept]
Audience: [who needs to learn this]
Misunderstandings: [what people get wrong]
Sources or examples: [docs, folders, screenshots, demos]
""",
    )

    if "technical_folder_assets" not in st.session_state:
        st.session_state.technical_folder_assets = {"documents": [], "images": [], "videos": []}
    if "technical_plan" not in st.session_state:
        st.session_state.technical_plan = {}
    if "technical_scenes" not in st.session_state:
        st.session_state.technical_scenes = []

    with st.expander("1. Topic and advisory intent", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            tech_topic = st.text_area("Topic or product concept", placeholder="Copilot Studio orchestration vs custom deterministic routing", height=90)
            tech_user_explanation = st.text_area(
                "Your explanation of the topic",
                placeholder="Explain the practical advisory story, why this matters, and what people need to understand.",
                height=130,
            )
            tech_misunderstandings = st.text_area(
                "Main misunderstandings to address",
                placeholder="- People think all routing options are interchangeable\n- People use orchestration when deterministic chat is better",
                height=110,
            )
        with col2:
            tech_feature_focus = st.text_area("Main feature aspect to highlight", placeholder="The decision rule for when orchestration is valuable", height=90)
            tech_audience = st.text_input("Target audience", value="Advisory, field, makers, and customer engineers")
            tech_duration = st.select_slider("Target length", ["60 seconds", "90 seconds", "2 minutes", "3 minutes"], value="90 seconds")
            tech_title_page = st.text_input("Title page text", placeholder="Orchestration Patterns: Choosing the Right Routing Model")
            tech_series_mode = st.checkbox(
                "Split large content into a learning series",
                value=True,
                help="When the source is broad, create a sequence of manageable parts instead of one dense video.",
            )
            tech_max_parts = st.slider("Maximum series parts", 2, 6, 4)

    with st.expander("2. Sources and reusable assets", expanded=True):
        learn_url = st.text_input("Any Microsoft Learn doc page URL", placeholder="https://learn.microsoft.com/...")
        folder_paths = st.text_area(
            "Local folder paths, one per line",
            placeholder="C:\\path\\to\\recording-or-demo-assets\nC:\\path\\to\\screenshots-or-docs",
            height=80,
        )
        existing_demo = st.text_input("Existing demo video or clip to include", placeholder="C:\\path\\to\\approved-demo-or-clip.mp4")

        source_col1, source_col2 = st.columns(2)
        with source_col1:
            if st.button("🔎 Gather sources and build plan", type="primary", use_container_width=True):
                try:
                    learn_source = _fetch_learn_page(learn_url) if learn_url.strip() else {}
                    folder_assets = _scan_explainer_folder(folder_paths)
                    if existing_demo.strip() and Path(existing_demo.strip().strip('"')).exists():
                        folder_assets.setdefault("videos", []).insert(0, {
                            "name": Path(existing_demo.strip().strip('"')).name,
                            "path": str(Path(existing_demo.strip().strip('"'))),
                        })
                    st.session_state.technical_folder_assets = folder_assets
                    st.session_state.technical_plan = _build_technical_explainer_plan(
                        topic=tech_topic,
                        user_explanation=tech_user_explanation,
                        misunderstandings=tech_misunderstandings,
                        feature_focus=tech_feature_focus,
                        audience=tech_audience,
                        title_page=tech_title_page,
                        learn_source=learn_source,
                        folder_assets=folder_assets,
                        series_mode=tech_series_mode,
                        max_parts=tech_max_parts,
                    )
                    st.session_state.technical_scenes = _technical_scenes_from_plan(st.session_state.technical_plan)
                    st.success("Plan and editable storyboard created.")
                except Exception as e:
                    st.error(f"Could not gather sources: {e}")
        with source_col2:
            if st.session_state.technical_folder_assets:
                assets = st.session_state.technical_folder_assets
                st.caption(
                    f"Source library: {len(assets.get('documents', []))} document/code file(s), "
                    f"{len(assets.get('images', []))} image(s), {len(assets.get('videos', []))} video(s)."
                )

    if st.session_state.technical_plan:
        st.markdown("### 3. Review content plan and self-critique")
        st.code(_format_technical_plan(st.session_state.technical_plan), language="markdown")

    if st.session_state.technical_scenes:
        st.markdown("### 4. Edit storyboard before generation")
        st.caption("Each scene has one job: correct a misconception, explain the mental model, cite a source, or make the decision rule memorable.")
        for i, scene in enumerate(st.session_state.technical_scenes):
            with st.container(border=True):
                st.markdown(f"#### Scene {i + 1}")
                col1, col2, col3 = st.columns([1.2, 1, 1])
                with col1:
                    st.session_state.technical_scenes[i]["title"] = st.text_input("Title", scene.get("title", ""), key=f"tech_title_{i}")
                with col2:
                    layouts = ["Title card", "Two-column", "Process", "Checklist", "Spotlight", "Image spotlight"]
                    st.session_state.technical_scenes[i]["layout"] = st.selectbox(
                        "Layout",
                        layouts,
                        index=layouts.index(scene.get("layout", "Spotlight")) if scene.get("layout", "Spotlight") in layouts else 0,
                        key=f"tech_layout_{i}",
                    )
                with col3:
                    styles = ["Executive dark", "Coral energy", "Berry premium", "Clean light"]
                    st.session_state.technical_scenes[i]["style"] = st.selectbox(
                        "Style",
                        styles,
                        index=styles.index(scene.get("style", "Executive dark")) if scene.get("style", "Executive dark") in styles else 0,
                        key=f"tech_style_{i}",
                    )
                image_options = ["No image"] + [item["path"] for item in st.session_state.technical_folder_assets.get("images", [])]
                current = scene.get("image_path") if scene.get("image_path") in image_options else "No image"
                selected = st.selectbox("Image/screenshot", image_options, index=image_options.index(current), key=f"tech_image_{i}")
                st.session_state.technical_scenes[i]["image_path"] = "" if selected == "No image" else selected
                if selected != "No image":
                    st.image(selected, caption="Selected explanatory visual", use_container_width=True)
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.session_state.technical_scenes[i]["bullets"] = st.text_area("Visual bullets", scene.get("bullets", ""), key=f"tech_bullets_{i}", height=90)
                with col2:
                    st.session_state.technical_scenes[i]["narration"] = st.text_area("Narration", scene.get("narration", ""), key=f"tech_narr_{i}", height=120)

        st.markdown("### 5. Generate explainer")
        tech_voice = st.selectbox("Voice", [
            "en-US-JennyNeural (Female)",
            "en-US-AriaNeural (Female)",
            "en-US-AndrewNeural (Male)",
            "en-US-BrianNeural (Male)",
        ], key="tech_voice")
        approved = st.checkbox("I reviewed the storyboard and self-critique. Generate this explainer.", key="tech_approved")
        if st.button("▶️ Generate technical explainer", type="primary", disabled=not approved):
            work_dir = Path(tempfile.mkdtemp(prefix="technical_explainer_"))
            output_path = str(work_dir / "technical_explainer.mp4")
            with st.spinner("Generating technical explainer..."):
                try:
                    from video_creator import VideoCreator

                    script = _build_video_script(
                        st.session_state.technical_plan.get("title", "Technical explainer"),
                        tech_voice,
                        "+8%",
                        st.session_state.technical_scenes,
                    )
                    creator = VideoCreator(script=script)
                    creator.generate(output_path)
                    st.success("✅ Technical explainer generated.")
                    st.video(output_path)
                    with open(output_path, "rb") as f:
                        st.download_button(
                            "⬇️ Download Technical Explainer",
                            f.read(),
                            file_name="technical_explainer.mp4",
                            mime="video/mp4",
                            type="primary",
                        )
                except Exception as e:
                    st.error(f"Error: {e}")


# ── Test Gallery ─────────────────────────────────────────────────────────────
elif tool == "🧪 Test Gallery":
    st.markdown("""
    <div class="cat-hero">
        <div class="cat-eyebrow">Demo library</div>
        <h1>Test Gallery</h1>
        <p>
            Review the app's current generated demos, clips, learning-series videos,
            and reference assets in one curated place. This page is for checking
            what the product can produce, not for browsing every intermediate file.
        </p>
    </div>
    """, unsafe_allow_html=True)

    manifest = _load_demo_manifest()
    demos = manifest.get("demos", [])

    if not demos:
        st.info("No demos are configured yet. Add entries to `test/demo_manifest.yaml`.")
    else:
        visible_demos = [
            demo for demo in demos
            if _demo_group(demo) in {
                "Featured videos",
                "Created videos",
                "Example outputs",
                "Featured app demos",
                "Web walkthroughs",
                "Evaluation learning series",
                "Generated clips",
            }
        ]
        grouped = {
            "Featured videos": [],
            "Created videos": [],
            "Example outputs": [],
            "Featured app demos": [],
            "Web walkthroughs": [],
            "Evaluation learning series": [],
            "Generated clips": [],
        }
        for demo in visible_demos:
            grouped.setdefault(_demo_group(demo), []).append(demo)
        for name in grouped:
            grouped[name] = sorted(grouped[name], key=_workflow_order_key)

        available = sum(1 for demo in visible_demos if (path := _demo_media_path(demo)) and path.exists())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Gallery items", len(visible_demos))
        m2.metric("Playable media", available)
        m3.metric("Final featured", len(grouped["Featured videos"]))
        m4.metric("Webinar clips", len(grouped["Generated clips"]))

        def render_demo_card(demo: dict, *, compact: bool = False, thumbnail_only: bool = False):
            title = _demo_display_title(demo)
            media_path = _demo_media_path(demo)
            thumbnail_path = _demo_thumbnail_path(demo)
            config_path = _resolve_demo_path(demo.get("config", ""))
            source_path = _resolve_demo_path(demo.get("source", ""))
            tags = demo.get("tags") or []

            with st.container(border=True):
                st.markdown(f"### {title}" if not compact else f"#### {title}")
                st.caption(_friendly_demo_label(demo))
                if demo.get("description"):
                    st.write(demo["description"])
                if tags:
                    st.caption(" · ".join(str(tag) for tag in tags[:6]))

                if thumbnail_only and thumbnail_path and thumbnail_path.exists():
                    st.image(str(thumbnail_path), use_container_width=True)
                    if media_path and media_path.exists():
                        st.caption(f"Media: {media_path.name}")
                elif media_path and media_path.exists():
                    st.video(str(media_path))
                elif media_path:
                    st.warning(f"Media not found: `{media_path}`")
                else:
                    st.info("No playable media configured for this item.")

                details = []
                if config_path:
                    details.append(("Config", config_path))
                if source_path:
                    details.append(("Source/reference", source_path))
                if media_path:
                    details.append(("Media", media_path))
                if details:
                    with st.expander("Files"):
                        for label, path in details:
                            exists = "exists" if path.exists() else "missing"
                            st.code(f"{label}: {path} ({exists})")

        st.markdown('<div class="section-kicker">Featured finals</div>', unsafe_allow_html=True)
        st.markdown("## Final videos")
        st.caption("Only videos marked final and featured get this polished thumbnail spot.")
        if grouped["Featured videos"]:
            cols = st.columns(3)
            for idx, demo in enumerate(grouped["Featured videos"]):
                with cols[idx % 3]:
                    render_demo_card(demo, compact=True, thumbnail_only=True)
        else:
            st.info("No final featured videos found.")

        st.divider()
        created_videos = grouped["Featured videos"] + grouped["Created videos"] + grouped["Featured app demos"] + grouped["Web walkthroughs"]
        if created_videos:
            st.markdown('<div class="section-kicker">Created videos</div>', unsafe_allow_html=True)
            st.markdown("## Created video library")
            st.caption("Group and filter generated videos by tool, topic, and draft/final status.")

            tools = sorted({_created_video_tool(demo) for demo in created_videos})
            topics = sorted({_created_video_topic(demo) for demo in created_videos})
            statuses = sorted({_created_video_status(demo) for demo in created_videos})
            f1, f2, f3 = st.columns(3)
            with f1:
                selected_tool = st.selectbox("Tool", ["All tools", *tools])
            with f2:
                selected_topic = st.selectbox("Topic", ["All topics", *topics])
            with f3:
                selected_status = st.selectbox("Status", ["All statuses", *statuses])

            filtered_created = [
                demo for demo in created_videos
                if (selected_tool == "All tools" or _created_video_tool(demo) == selected_tool)
                and (selected_topic == "All topics" or _created_video_topic(demo) == selected_topic)
                and (selected_status == "All statuses" or _created_video_status(demo) == selected_status)
            ]

            if filtered_created:
                for tool_name in sorted({_created_video_tool(demo) for demo in filtered_created}):
                    st.markdown(f"### {tool_name}")
                    tool_demos = [demo for demo in filtered_created if _created_video_tool(demo) == tool_name]
                    for topic_name in sorted({_created_video_topic(demo) for demo in tool_demos}):
                        st.caption(f"Topic: {topic_name}")
                        cols = st.columns(2)
                        for idx, demo in enumerate([d for d in tool_demos if _created_video_topic(d) == topic_name]):
                            with cols[idx % 2]:
                                render_demo_card(demo, compact=True)
            else:
                st.info("No created videos match the selected filters.")

            st.divider()

        tab_labels = [
            f"Example outputs ({len(grouped['Example outputs']) + len(grouped['Evaluation learning series'])})",
            f"Reference clips ({len(grouped['Generated clips'])})",
        ]
        series_tab, clips_tab = st.tabs(tab_labels)

        with series_tab:
            st.markdown("### Technical Studio example outputs")
            st.caption("Course-style examples generated from Technical Explainer Studio.")
            for demo in grouped["Example outputs"]:
                render_demo_card(demo, compact=True)
            for demo in grouped["Evaluation learning series"]:
                render_demo_card(demo, compact=True)

        with clips_tab:
            st.markdown("### Reference clips")
            st.caption("These are publishable clip examples extracted from a longer recording, not the old sample demo clips.")
            clip_cols = st.columns(2)
            for idx, demo in enumerate(grouped["Generated clips"]):
                with clip_cols[idx % 2]:
                    render_demo_card(demo, compact=True)
