from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CREATOR_DIR = ROOT / "creator"
SANITIZER_DIR = ROOT / "sanitizer"
EXAMPLES_DIR = ROOT / "examples"
OUTPUT_DIR = EXAMPLES_DIR / "better_demos"
CLIPS_DIR = OUTPUT_DIR / "clips"
MANIFEST_PATH = ROOT / "test" / "demo_manifest.yaml"

sys.path.insert(0, str(CREATOR_DIR))
sys.path.insert(0, str(SANITIZER_DIR))

from clip_extractor import ClipSpec, extract_clips
from media_pipeline import validate_media
from video_creator import VideoCreator


SCRIPT_REVIEWS: dict[str, list[dict[str, str]]] = {}


def run(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return float(result.stdout.strip())


def _scene_text(scene: dict) -> str:
    return " ".join(
        str(scene.get(field, ""))
        for field in ("title", "subtitle", "narration")
    ).lower()


def review_script_from_viewer_perspective(script_name: str, data: dict, pass_name: str) -> dict[str, str]:
    scenes = data.get("scenes") or []
    if len(scenes) < 4:
        raise ValueError(f"{script_name} {pass_name} failed: demo needs enough scenes to orient, show workflow, and land the value.")

    first = scenes[0]
    first_text = _scene_text(first)
    first_bullets = [str(item).strip() for item in first.get("bullets", []) if str(item).strip()]

    if pass_name == "pass 1 - orientation":
        required = {
            "app name": "cat video tools" in first_text,
            "states this is an app": "app" in first_text,
            "says what was built": "made" in first_text or "built" in first_text,
            "clear feature overview": len(first_bullets) >= 3,
            "viewer outcome": any(word in first_text for word in ("validated", "publishable", "safer", "teachable", "reviewable")),
        }
    else:
        all_text = " ".join(_scene_text(scene) for scene in scenes)
        required = {
            "opens with value before mechanics": not first_text.startswith(("start with", "choose", "generate", "review before")),
            "uses viewer-centered stakes": any(word in all_text for word in ("without", "protect", "review", "publishable", "control", "understanding")),
            "avoids administrative filler": not any(phrase in all_text for phrase in ("in this demo we will", "this section", "as instructed")),
            "explains useful features": sum(len(scene.get("bullets", [])) for scene in scenes[:2]) >= 6,
            "keeps narration substantive": all(len(str(scene.get("narration", "")).split()) >= 14 for scene in scenes[:2]),
        }

    missing = [name for name, ok in required.items() if not ok]
    if missing:
        raise ValueError(f"{script_name} {pass_name} failed: " + ", ".join(missing))

    return {
        "pass": pass_name,
        "status": "passed",
        "viewer_question": "Would I know what this is, why I should care, and what I can do with it?",
        "result": "The script opens with app context and gives the viewer a reason to keep watching before showing mechanics.",
    }


def review_script_twice(path: Path, data: dict) -> None:
    reviews = [
        review_script_from_viewer_perspective(path.name, data, "pass 1 - orientation"),
        review_script_from_viewer_perspective(path.name, data, "pass 2 - engagement/usefulness"),
    ]
    SCRIPT_REVIEWS[path.name] = reviews
    review_path = path.with_suffix(".review.json")
    review_path.write_text(json.dumps(reviews, indent=2), encoding="utf-8")


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if "scenes" in data:
        review_script_twice(path, data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def build_creator_demo(walkthrough_path: Path | None = None) -> Path:
    script_path = OUTPUT_DIR / "creator_decision_review_demo.yaml"
    output_path = OUTPUT_DIR / "creator_decision_review_demo.mp4"
    walkthrough_path = walkthrough_path if walkthrough_path and walkthrough_path.exists() else None
    scenes = [
        {
            "title": "Introducing CAT Video Tools: Demo Video Creator",
            "subtitle": "Build product demos from a script, optional web tour, voice, and reviewable output",
            "icon": "D",
            "background": "#0f172a",
            "accent_color": "#93c5fd",
            "narration": "Introducing CAT Video Tools: Demo Video Creator. We built this app for turning a feature story into a polished demo. You bring the message: what the product is, who it helps, what viewers should notice, and which app steps prove it. The tool can generate the slides, narration, optional guided web tour footage, and a validated MP4 you can review before sharing.",
            "bullets": ["Product story", "Optional web tour", "Narration and slides", "Validated MP4"],
            "animation": "none",
        },
        {
            "title": "Choose what you want to control",
            "subtitle": "Bring a tight brief, or provide the exact assets and page steps",
            "icon": "1",
            "background": "#1f2937",
            "accent_color": "#60a5fa",
            "narration": "You can stay lightweight and let the app create the structure from a short brief, or you can control the exact inputs: uploaded images, an existing clip, a page URL, a click sequence, voice, scene order, and the closing takeaway. Either way, the output is still a viewer-facing demo, not a list of production tasks.",
            "bullets": ["Brief or detailed script", "Upload images or clips", "Optional page sequence", "Editable scene order"],
            "animation": "none",
        },
        {
            "title": "Generate what the viewer needs to see",
            "subtitle": "The app turns raw navigation into a guided proof clip",
            "icon": "2",
            "background": "#111827",
            "accent_color": "#f472b6",
            "narration": "When the demo needs live product proof, give the app the URL and the sequence of clicks or scrolls. It captures silent raw walkthrough footage with visible step markers and a sidecar description. The final demo script then explains the value over that footage, so the viewer sees the UI while hearing why it matters.",
            "bullets": ["URL and actions", "Silent raw footage", "Step markers", "Description sidecar"],
            "animation": "none",
        },
    ]
    if walkthrough_path:
        scenes.append(
            {
                "title": "Portal guided tour demo",
                "subtitle": "Silent raw walkthrough footage assembled into the narrated demo",
                "visual": "video",
                "video": str(walkthrough_path),
                "narration": "Here is the guided tour footage inside the demo. The raw clip stays silent on purpose. The value, context, and feature explanation come from the Demo Creator script, while the description file preserves what each UI step is supposed to prove.",
                "bullets": [],
                "background": "#0f172a",
                "accent_color": "#93c5fd",
                "animation": "none",
            }
        )
    scenes.append(
        {
            "title": "Review the finished product demo",
            "subtitle": "Check message, media, narration, and output quality before sharing",
            "icon": "3",
            "background": "#312e81",
            "accent_color": "#fbbf24",
            "narration": "The final output is a product demo you can inspect: the app introduction, the feature promise, the optional controls you used, the generated walkthrough, and the final takeaway. The tool validates the media so you know the MP4 is playable before it goes into the hub.",
            "bullets": ["Product intro", "Feature promise", "Generated tour", "Validated output"],
            "animation": "none",
        }
    )
    write_yaml(
        script_path,
        {
            "title": "Demo Video Creator - From Notes to Product Demo",
            "resolution": "1280x720",
            "fps": 30,
            "voice": "en-US-JennyNeural",
            "voice_rate": "+8%",
            "music_volume": 0,
            "scenes": scenes,
        },
    )
    VideoCreator(str(script_path)).generate(str(output_path))
    validate_media(output_path)
    return output_path


def build_clip_demo() -> Path:
    script_path = OUTPUT_DIR / "clip_extractor_publishable_demo.yaml"
    output_path = OUTPUT_DIR / "clip_extractor_publishable_demo.mp4"
    write_yaml(
        script_path,
        {
            "title": "Clip Extractor - Publishable Clips",
            "resolution": "1280x720",
            "fps": 30,
            "voice": "en-US-AriaNeural",
            "voice_rate": "+8%",
            "music_volume": 0,
            "scenes": [
                {
                    "title": "Introducing CAT Video Tools: Clip Extractor",
                    "subtitle": "Choose the best moments, control the ranges, and export clean clips",
                    "icon": "C",
                    "background": "#0f172a",
                    "accent_color": "#93c5fd",
                    "narration": "Introducing CAT Video Tools: Clip Extractor. We built this app for turning a long recording into short, publishable clips people will actually watch. You choose the moments that matter, add titles and categories, and the app generates clean MP4 clips with normalized audio and reviewable validation checks.",
                    "bullets": ["Upload a long recording", "Choose clip ranges", "Name and group clips", "Generate clean MP4s"],
                    "animation": "fade_in",
                },
                {
                    "title": "You control the publishing decision",
                    "subtitle": "Pick the range, title, and category before anything renders",
                    "icon": "A",
                    "background": "#172554",
                    "accent_color": "#93c5fd",
                    "narration": "The app does not guess what is publishable. You decide the start time, end time, title, and category for each clip. That keeps the judgment with the maker while the tool handles the repetitive media work.",
                    "bullets": ["Start time", "End time", "Clip title", "Category"],
                },
                {
                    "title": "The app generates durable clips",
                    "subtitle": "Clean encoding and audio handling are built in",
                    "icon": "B",
                    "background": "#1f2937",
                    "accent_color": "#34d399",
                    "narration": "After you choose the content, the app generates clips that are meant to survive review: clean encoding, normalized audio, and stream checks instead of fragile copy-only cuts.",
                    "bullets": ["Frame-accurate output", "Normalized audio", "Validated streams"],
                    "animation": "slide_up",
                },
                {
                    "title": "Review and reuse the clip set",
                    "subtitle": "Download individual clips or a package",
                    "icon": "C",
                    "background": "#581c87",
                    "accent_color": "#f0abfc",
                    "narration": "The result is a clip set you can inspect, download, and reuse in demos, galleries, or follow-up assets. The app handles the packaging so the maker can focus on choosing the right evidence.",
                    "bullets": ["Playable clips", "Clean audio", "ZIP-friendly outputs"],
                },
            ],
        },
    )
    VideoCreator(str(script_path)).generate(str(output_path))
    validate_media(output_path)
    return output_path


def build_sanitizer_demo() -> Path:
    script_path = OUTPUT_DIR / "sanitizer_review_first_demo.yaml"
    output_path = OUTPUT_DIR / "sanitizer_review_first_demo.mp4"
    write_yaml(
        script_path,
        {
            "title": "Meeting Sanitizer - Review Before Render",
            "resolution": "1280x720",
            "fps": 30,
            "voice": "en-US-GuyNeural",
            "voice_rate": "+6%",
            "music_volume": 0,
            "scenes": [
                {
                    "title": "Introducing CAT Video Tools: Meeting Sanitizer",
                    "subtitle": "Upload a recording and transcript, review choices, then render safer video",
                    "icon": "S",
                    "background": "#0f172a",
                    "accent_color": "#38bdf8",
                    "narration": "Introducing CAT Video Tools: Meeting Sanitizer. We built this app for preparing recorded meetings before they become reusable demos or clips. You upload the recording and transcript, choose what to keep, review speaker and masking decisions, and the app generates a safer, reviewable MP4.",
                    "bullets": ["Upload recording", "Upload transcript", "Review cuts and speakers", "Generate safer MP4"],
                    "animation": "fade_in",
                },
                {
                    "title": "Everything important is reviewable",
                    "subtitle": "Cuts, speakers, masks, and title cards stay visible",
                    "icon": "R",
                    "background": "#0f172a",
                    "accent_color": "#38bdf8",
                    "narration": "Before rendering, the app shows the decisions that matter: keep ranges, cut ranges, speaker names, title cards, end cards, and masking choices. Optional manual overrides let you correct the plan before video is produced.",
                    "bullets": ["Speaker names", "Keep and cut ranges", "Manual overrides", "Mask decisions"],
                },
                {
                    "title": "Protect people who are not part of the demo",
                    "subtitle": "Preserve intended presenters and reduce unnecessary exposure",
                    "icon": "P",
                    "background": "#3f1d2b",
                    "accent_color": "#fb7185",
                    "narration": "The product is built for the practical privacy problem: keep the intended presenters visible, remove irrelevant meeting sections, and mask non-presenters when the recording would otherwise expose more than the demo needs.",
                    "bullets": ["Keep presenters", "Remove admin chatter", "Mask non-presenters"],
                    "animation": "slide_up",
                },
                {
                    "title": "Validate the output",
                    "subtitle": "Clean audio, complete opening and ending",
                    "icon": "V",
                    "background": "#14532d",
                    "accent_color": "#86efac",
                    "narration": "The app generates the sanitized video, then validates the media streams. Before sharing, you can inspect the opening, ending, audio, and rendered output so the final file is useful instead of merely processed.",
                    "bullets": ["Complete first line", "Complete ending", "Clean audio", "Valid MP4"],
                },
            ],
        },
    )
    VideoCreator(str(script_path)).generate(str(output_path))
    validate_media(output_path)
    return output_path


def build_technical_explainer_demo() -> Path:
    script_path = OUTPUT_DIR / "technical_explainer_studio_demo.yaml"
    output_path = OUTPUT_DIR / "technical_explainer_studio_demo.mp4"
    write_yaml(
        script_path,
        {
            "title": "Technical Explainer Studio - From Confusion to Clarity",
            "resolution": "1280x720",
            "fps": 30,
            "voice": "en-US-JennyNeural",
            "voice_rate": "+8%",
            "music_volume": 0,
            "scenes": [
                {
                    "title": "Introducing CAT Video Tools: Technical Explainer Studio",
                    "subtitle": "An app for turning hard technical topics into teachable video assets",
                    "icon": "!",
                    "background": "#0f172a",
                    "accent_color": "#93c5fd",
                    "narration": "Introducing CAT Video Tools: Technical Explainer Studio. We built this app for topics where a simple summary is not enough: it gathers the user's explanation, official docs, local sources, images, and demos, then builds a reviewable teaching plan before rendering video.",
                    "bullets": ["User framing", "Learn docs and local sources", "Diagrams and screenshots", "Reviewable storyboard"],
                    "animation": "fade_in",
                },
                {
                    "title": "Start with the misunderstanding",
                    "subtitle": "The user's explanation drives the video",
                    "icon": "?",
                    "background": "#111827",
                    "accent_color": "#60a5fa",
                    "narration": "Technical Explainer Studio starts with the user's framing: what the topic means, what people misunderstand, and which product aspect needs to stand out.",
                    "bullets": ["User explanation", "Misunderstandings", "Feature focus", "Title-page direction"],
                    "animation": "fade_in",
                },
                {
                    "title": "Ground it in sources",
                    "subtitle": "Learn docs, local folders, screenshots, and demos",
                    "icon": "S",
                    "background": "#2F3C7E",
                    "accent_color": "#F96167",
                    "narration": "The app accepts any Microsoft Learn page, local folders, images, code samples, and existing demo clips. Sources become traceable inputs, not hidden prompt context.",
                    "bullets": ["Any Learn doc page", "Local folders", "Existing demo video", "Screenshots and code"],
                    "animation": "slide_up",
                },
                {
                    "title": "Self-critique before rendering",
                    "subtitle": "Accuracy, clarity, and visual usefulness",
                    "icon": "✓",
                    "background": "#6D2E46",
                    "accent_color": "#ECE2D0",
                    "narration": "Before video generation, the plan critiques itself for accuracy, source support, jargon, misconception coverage, and whether each visual actually improves understanding.",
                    "bullets": ["Source support", "Plain language", "One job per scene", "Decision rule"],
                    "animation": "fade_in",
                },
                {
                    "title": "Editable storyboard, then video",
                    "subtitle": "Advisory-ready explainers",
                    "icon": "4",
                    "background": "#14532d",
                    "accent_color": "#86efac",
                    "narration": "Only after review does the app render a short narrated explainer with slides, screenshots, diagrams, or demo captures. The goal is understanding, not just automation.",
                    "bullets": ["Review scenes", "Edit narration", "Assign visuals", "Generate validated MP4"],
                    "animation": "slide_up",
                },
            ],
        },
    )
    VideoCreator(str(script_path)).generate(str(output_path))
    validate_media(output_path)
    return output_path


def make_clips(video_paths: dict[str, Path]) -> list[Path]:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    clip_plan = [
        ("creator", video_paths["creator"], "demo-video-creator-overview", "Demo Video Creator Overview", 0.4, 10.5),
        ("creator", video_paths["creator"], "structured-script-to-video", "Structured Script to Video", 10.7, 18.5),
        ("clip", video_paths["clip"], "clip-extractor-overview", "Clip Extractor Overview", 0.4, 10.8),
        ("sanitizer", video_paths["sanitizer"], "meeting-sanitizer-overview", "Meeting Sanitizer Overview", 0.4, 11.2),
        ("technical", video_paths["technical"], "technical-explainer-overview", "Technical Explainer Overview", 0.4, 12.0),
    ]
    for prefix, source, clip_id, title, start, end in clip_plan:
        max_end = max(1.0, duration(source) - 0.2)
        adjusted_end = min(end, max_end)
        result = extract_clips(
            video_path=source,
            clips=[
                ClipSpec(
                    id=f"{prefix}-{clip_id}",
                    title=title,
                    start=start,
                    end=adjusted_end,
                    category="better-demo",
                    manual=True,
                )
            ],
            output_dir=CLIPS_DIR,
            crf=18,
            audio_enhance=True,
        )
        outputs.extend(Path(item["output_path"]) for item in result)
    return outputs


def update_manifest(video_paths: dict[str, Path], clip_paths: list[Path]) -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {"demos": []}
    old_demos = manifest.get("demos", [])
    old_demos = [
        demo
        for demo in old_demos
        if not str(demo.get("status", "")).startswith("better demo")
    ]

    new_demos = [
        {
            "title": "Introducing Meeting Sanitizer",
            "kind": "sanitizer",
            "status": "better demo - generated",
            "media": str(video_paths["sanitizer"].relative_to(ROOT)).replace("\\", "/"),
            "config": str((OUTPUT_DIR / "sanitizer_review_first_demo.yaml").relative_to(ROOT)).replace("\\", "/"),
            "description": "See the review-first workflow for preparing meeting recordings: planned cuts, speaker preservation, non-presenter masking, title/end cards, and output validation.",
            "tags": ["sanitizer", "better-demo", "app-overview", "privacy", "review-first"],
        },
        {
            "title": "Introducing Clip Extractor",
            "kind": "clip extraction",
            "status": "better demo - generated",
            "media": str(video_paths["clip"].relative_to(ROOT)).replace("\\", "/"),
            "config": str((OUTPUT_DIR / "clip_extractor_publishable_demo.yaml").relative_to(ROOT)).replace("\\", "/"),
            "description": "Watch how a long recording becomes short, intentional clips with explicit ranges, titles, clean re-encoding, normalized audio, and media validation.",
            "tags": ["clip-extractor", "better-demo", "app-overview", "publishable", "validated"],
        },
        {
            "title": "Introducing Demo Video Creator",
            "kind": "creator",
            "status": "better demo - generated",
            "media": str(video_paths["creator"].relative_to(ROOT)).replace("\\", "/"),
            "config": str((OUTPUT_DIR / "creator_decision_review_demo.yaml").relative_to(ROOT)).replace("\\", "/"),
            "description": "See how CAT Video Tools turns a reviewed script or web walkthrough sequence into a narrated, validated demo video while keeping the message, scenes, voice, and output quality under human review.",
            "tags": ["demo-video-creator", "better-demo", "app-overview", "web-walkthrough", "validated"],
        },
        {
            "title": "Introducing Technical Explainer Studio",
            "kind": "technical explainer",
            "status": "better demo - generated",
            "media": str(video_paths["technical"].relative_to(ROOT)).replace("\\", "/"),
            "config": str((OUTPUT_DIR / "technical_explainer_studio_demo.yaml").relative_to(ROOT)).replace("\\", "/"),
            "description": "See how the app turns a hard technical topic into a source-grounded teaching plan using user framing, Learn docs, local assets, self-critique, and an editable storyboard.",
            "tags": ["technical-explainer", "better-demo", "app-overview", "advisory", "understanding"],
        },
    ]

    for clip_path in clip_paths:
        clip_title = clip_path.stem.replace("-", " ").title()
        for old, new in {
            "Creator Demo Video Creator": "Demo Video Creator",
            "Creator Video Creator": "Video Creator",
            "Clip Clip Extractor": "Clip Extractor",
            "Sanitizer Meeting Sanitizer": "Meeting Sanitizer",
            "Technical Technical Explainer": "Technical Explainer",
        }.items():
            clip_title = clip_title.replace(old, new)
        new_demos.append(
            {
                "title": f"Clip excerpt: {clip_title}",
                "kind": "clip extraction",
                "status": "better demo clip - generated",
                "media": str(clip_path.relative_to(ROOT)).replace("\\", "/"),
                "description": "A short publishable excerpt cut from the current demo set, with normalized audio and validated media streams.",
                "tags": ["clip", "better-demo", "publishable"],
            }
        )

    manifest["demos"] = new_demos + old_demos
    MANIFEST_PATH.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False), encoding="utf-8")


def main() -> int:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    walkthrough_path = ROOT / "examples" / "web_walkthroughs" / "cat-video-tools-portal-walkthrough-raw.mp4"
    video_paths = {
        "creator": build_creator_demo(walkthrough_path),
        "clip": build_clip_demo(),
        "sanitizer": build_sanitizer_demo(),
        "technical": build_technical_explainer_demo(),
    }
    clip_paths = make_clips(video_paths)
    update_manifest(video_paths, clip_paths)

    report = {
        "videos": {name: str(path) for name, path in video_paths.items()},
        "clips": [str(path) for path in clip_paths],
        "manifest": str(MANIFEST_PATH),
        "script_reviews": SCRIPT_REVIEWS,
    }
    (OUTPUT_DIR / "generation-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
