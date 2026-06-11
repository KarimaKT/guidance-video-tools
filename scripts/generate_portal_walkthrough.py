from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CREATOR_DIR = ROOT / "creator"
SANITIZER_DIR = ROOT / "sanitizer"
OUTPUT_DIR = ROOT / "examples" / "web_walkthroughs"
MANIFEST_PATH = ROOT / "test" / "demo_manifest.yaml"

sys.path.insert(0, str(CREATOR_DIR))
sys.path.insert(0, str(SANITIZER_DIR))

from web_walkthrough import capture_web_walkthrough


URL = "http://localhost:8601"

STEPS = [
    {
        "label": "Open the portal",
        "action": "goto",
        "narration": "Introducing CAT Video Tools, a local hub for making recorded video useful: clean meeting recordings, extract strong clips, create guided product demos, and build deeper technical explainers.",
    },
    {
        "label": "Review workflow demos",
        "action": "scroll:0.28",
        "narration": "The hub is organized around outcomes, not tool chores. Each workflow includes proof of what it produces, so a maker can choose the right path before starting.",
    },
    {
        "label": "Compare the four workflows",
        "action": "scroll:0.62",
        "narration": "The four sections separate different jobs: privacy-safe meeting cleanup, publishable clips, product walkthroughs, and source-grounded teaching videos.",
    },
    {
        "label": "Open Test Gallery",
        "action": "click:Test Gallery",
        "narration": "The Test Gallery is the review surface. It keeps generated demos, walkthroughs, and clips visible so quality can be judged before anything is shared.",
    },
    {
        "label": "Open Meeting Sanitizer",
        "action": "click:Meeting Sanitizer",
        "narration": "Meeting Sanitizer helps make recordings safer to reuse by focusing on the intended speakers and reducing unnecessary exposure before a clip leaves the workspace.",
    },
    {
        "label": "Open Clip Extractor",
        "action": "click:Clip Extractor",
        "narration": "Clip Extractor turns a long recording into intentional evidence: a short segment with context, boundaries, and reviewable output.",
    },
    {
        "label": "Open Demo Video Creator",
        "action": "click:Demo Video Creator",
        "narration": "Demo Video Creator is for showing an app clearly. It combines a value-led script with guided web steps so the final tour explains what the product does for the viewer.",
    },
    {
        "label": "Show guided web tour builder",
        "action": "wait",
        "narration": "The guided tour builder captures the page sequence, step labels, and narration together, turning raw navigation into a coherent product story.",
    },
    {
        "label": "Open Technical Explainer Studio",
        "action": "click:Technical Explainer Studio",
        "narration": "Technical Explainer Studio has a different job: teaching. It uses source material, diagrams, and stronger narration when the viewer needs to understand a concept, not just watch a feature.",
    },
    {
        "label": "Conclude the portal tour",
        "action": "wait",
        "narration": "That is the hub pattern: pick the right video job, generate a reviewable artifact, and keep the message professional enough to reuse.",
    },
]


def update_manifest(video_path: Path, plan_path: Path) -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {"demos": []}
    demos = [
        demo
        for demo in manifest.get("demos", [])
        if demo.get("id") != "cat-video-tools-portal-walkthrough"
    ]
    demos.insert(
        0,
        {
            "id": "cat-video-tools-portal-walkthrough",
            "title": "Raw walkthrough: CAT Video Tools portal",
            "kind": "web walkthrough",
            "status": "raw web walkthrough - generated",
            "media": str(video_path.relative_to(ROOT)).replace("\\", "/"),
            "config": str(plan_path.relative_to(ROOT)).replace("\\", "/"),
            "description": "A silent guided web tour generated from the portal URL, visible step markers, a planned page sequence, and a sidecar description for the narrated assembly step.",
            "tags": ["guided-web-tour", "demo-video-creator", "portal", "raw", "silent"],
        },
    )
    manifest["demos"] = demos
    MANIFEST_PATH.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=False), encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "cat-video-tools-portal-walkthrough-raw.mp4"
    result = capture_web_walkthrough(
        url=URL,
        steps=STEPS,
        output_dir=OUTPUT_DIR,
        output_path=output_path,
        title="CAT Video Tools guided portal tour",
        voice="en-US-AriaNeural",
        voice_rate="+15%",
        max_screen_seconds=4.0,
        narrate=False,
    )
    update_manifest(Path(result["video"]), Path(result["plan"]))
    print(result["video"])
    print(result["plan"])
    print(result["description"])
    print(f"{result['summary']['duration']:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
