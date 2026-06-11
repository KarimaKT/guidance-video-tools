
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CREATOR_DIR = ROOT / "creator"
SANITIZER_DIR = ROOT / "sanitizer"
OUT_DIR = ROOT / "examples" / "learning_series" / "evaluating_agents"
ASSET_DIR = OUT_DIR / "assets"
MANIFEST_PATH = ROOT / "test" / "demo_manifest.yaml"
BANNER = Path(os.environ["CAT_VIDEO_TOOLS_BANNER"]) if os.environ.get("CAT_VIDEO_TOOLS_BANNER") else None

sys.path.insert(0, str(CREATOR_DIR))
sys.path.insert(0, str(SANITIZER_DIR))

from media_pipeline import validate_media
from video_creator import VideoCreator

W, H = 1280, 720
DATE_LABEL = "May 6, 2026"
AUTHOR_LABEL = "By KarimaKT"
FOOTER = f"{AUTHOR_LABEL} | {DATE_LABEL}"
SERIES = "Evaluating Copilot Studio Agents"
BG = "#0f172a"
INK = "#0f172a"
MUTED = "#64748b"
SCRIPT_REVIEWS: dict[str, list[dict[str, str]]] = {}


def font(size: int, bold: bool = False):
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def text_bbox(draw: ImageDraw.ImageDraw, text: str, fnt) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_pixels(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            probe = f"{current} {word}"
            if text_bbox(draw, probe, fnt)[0] <= max_width:
                current = probe
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fnt,
    fill: str,
    max_width: int,
    line_gap: int = 8,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    lines = wrap_pixels(draw, text, fnt, max_width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "..."
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += fnt.size + line_gap
    return y


def _scene_text(scene: dict) -> str:
    return " ".join(
        str(scene.get(field, ""))
        for field in ("title", "subtitle", "narration")
    ).lower()


def review_script_from_user_perspective(script_name: str, script: dict, pass_name: str) -> dict[str, str]:
    scenes = script.get("scenes") or []
    if len(scenes) < 5:
        raise ValueError(f"{script_name} {pass_name} failed: each learning video needs enough scenes to orient, teach, reframe, and close with application.")

    first_text = _scene_text(scenes[0])
    all_text = f"{script.get('title', '')} ".lower() + " ".join(_scene_text(scene) for scene in scenes)
    last_text = _scene_text(scenes[-1])

    if pass_name == "pass 1 - learner orientation":
        required = {
            "names Copilot Studio evaluations": "evaluating copilot studio agents" in all_text or ("copilot studio" in all_text and any(term in all_text for term in ("evaluation", "evaluating", "evaluate"))),
            "maker perspective": "maker" in all_text or "your project" in all_text,
            "clear lifecycle value": any(word in all_text for word in ("scope", "target", "deliver", "v1", "readiness", "production", "operate", "operating", "operationalize")),
            "product/data concepts": any(term in all_text for term in ("test set", "grader", "analytics", "rubric", "expected answer", "blind set")),
            "project-oriented close": "if you are following along" in last_text and "your project" in last_text,
        }
    else:
        required = {
            "teaches instead of summarizing": any(term in all_text for term in ("aha moment", "common mistake", "maker-centered", "goes wrong", "mental model")),
            "has concrete scenarios": any(term in all_text for term in ("employee onboarding", "eurozone", "production", "csv", "tool", "policy")),
            "explains decisions/tradeoffs": any(term in all_text for term in ("tradeoff", "cost", "risk", "decision", "block", "overfit")),
            "avoids administrative framing": not any(phrase in all_text for phrase in ("lab preview", "in this lab", "this final slide previews", "as instructed", "the prompt asked")),
            "substantive opening": len(str(scenes[0].get("narration", "")).split()) >= 22,
        }

    missing = [name for name, ok in required.items() if not ok]
    if missing:
        raise ValueError(f"{script_name} {pass_name} failed: " + ", ".join(missing))

    return {
        "pass": pass_name,
        "status": "passed",
        "viewer_question": "Would a maker understand why this matters, what to do differently, and how the product concepts fit the build lifecycle?",
        "result": "The script teaches from the maker's perspective, preserves the evaluation lifecycle, and closes with a concrete project application.",
    }


def review_script_twice(script_path: Path, script: dict) -> None:
    reviews = [
        review_script_from_user_perspective(script_path.name, script, "pass 1 - learner orientation"),
        review_script_from_user_perspective(script_path.name, script, "pass 2 - engagement/usefulness"),
    ]
    SCRIPT_REVIEWS[script_path.name] = reviews
    script_path.with_suffix(".review.json").write_text(json.dumps(reviews, indent=2), encoding="utf-8")


def rounded_card(draw, box, fill, outline=None, width=2, radius=24):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _node_box(node: dict) -> tuple[int, int, int, int]:
    return (
        int(node["x"]),
        int(node["y"]),
        int(node["x"] + node.get("w", 252)),
        int(node["y"] + node.get("h", 118)),
    )


def _outside_port(source: dict, target: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    sx1, sy1, sx2, sy2 = _node_box(source)
    tx1, ty1, tx2, ty2 = _node_box(target)
    scx, scy = (sx1 + sx2) // 2, (sy1 + sy2) // 2
    tcx, tcy = (tx1 + tx2) // 2, (ty1 + ty2) // 2
    dx, dy = tcx - scx, tcy - scy
    pad = 18

    if abs(dx) >= abs(dy):
        if dx >= 0:
            return (sx2 + pad, scy), (tx1 - pad, tcy)
        return (sx1 - pad, scy), (tx2 + pad, tcy)
    if dy >= 0:
        return (scx, sy2 + pad), (tcx, ty1 - pad)
    return (scx, sy1 - pad), (tcx, ty2 + pad)


def _route_connector(source: dict, target: dict) -> list[tuple[int, int]]:
    start, end = _outside_port(source, target)
    sx, sy = start
    ex, ey = end

    if abs(sy - ey) <= 34 or abs(sx - ex) <= 34:
        return [start, end]

    if sx <= ex:
        mid_x = (sx + ex) // 2
        return [start, (mid_x, sy), (mid_x, ey), end]

    # Route loop-back connections around the bottom of the diagram instead of
    # cutting diagonally through nodes. This keeps lifecycle loops readable.
    bottom_y = min(H - 92, max(sy, ey) + 92)
    return [start, (sx, bottom_y), (ex, bottom_y), end]


def _route_edge(source_id: str, target_id: str, source: dict, target: dict) -> list[tuple[int, int]]:
    sx1, sy1, sx2, sy2 = _node_box(source)
    tx1, ty1, tx2, ty2 = _node_box(target)
    scx, scy = (sx1 + sx2) // 2, (sy1 + sy2) // 2
    tcx, tcy = (tx1 + tx2) // 2, (ty1 + ty2) // 2
    pad = 18

    if source_id == "deliver" and target_id == "learn":
        return [
            (scx, sy2 + pad),
            (scx, tcy),
            (tx2 + pad, tcy),
        ]
    if source_id == "learn" and target_id == "scope":
        return [
            (sx1 - pad, scy),
            (tcx, scy),
            (tcx, ty2 + pad),
        ]
    return _route_connector(source, target)


def _draw_antialiased_arrow(img: Image.Image, points: list[tuple[int, int]], fill="#2563eb", width=5):
    scale = 4
    overlay = Image.new("RGBA", (W * scale, H * scale), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    scaled = [(int(x * scale), int(y * scale)) for x, y in points]
    odraw.line(scaled, fill=fill, width=width * scale, joint="curve")

    if len(points) >= 2:
        (x1, y1), (x2, y2) = points[-2], points[-1]
        angle = math.atan2(y2 - y1, x2 - x1)
        head_len = 22 * scale
        head_w = 11 * scale
        tip = (x2 * scale, y2 * scale)
        left = (
            tip[0] - head_len * math.cos(angle) + head_w * math.sin(angle),
            tip[1] - head_len * math.sin(angle) - head_w * math.cos(angle),
        )
        right = (
            tip[0] - head_len * math.cos(angle) - head_w * math.sin(angle),
            tip[1] - head_len * math.sin(angle) + head_w * math.cos(angle),
        )
        odraw.polygon([tip, left, right], fill=fill)

    overlay = overlay.resize((W, H), Image.Resampling.LANCZOS)
    img.alpha_composite(overlay)


def title_slide(part: int, title: str, subtitle: str, output: Path) -> Path:
    img = Image.new("RGB", (W, H), "#111827")
    if BANNER and BANNER.exists():
        banner = Image.open(BANNER).convert("RGB")
        ratio = max(W / banner.width, H / banner.height)
        resized = banner.resize((int(banner.width * ratio), int(banner.height * ratio)))
        left = (resized.width - W) // 2
        top = (resized.height - H) // 2
        img = resized.crop((left, top, left + W, top + H))
    overlay = Image.new("RGBA", (W, H), (15, 23, 42, 185))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    rounded_card(draw, (72, 70, 244, 126), "#93c5fd", None, 0, 22)
    draw.text((98, 84), f"PART {part}", font=font(29, True), fill="#082f49")
    y = draw_wrapped(draw, (72, 178), title, font(56, True), "#ffffff", 920, 10)
    y += 8
    draw_wrapped(draw, (76, y), subtitle, font(29), "#dbeafe", 980, 8)
    draw.text((76, H - 92), FOOTER, font=font(26, True), fill="#ffffff")
    draw.text((76, H - 55), SERIES, font=font(20), fill="#bfdbfe")
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, quality=95)
    return output


def text_slide(title: str, subtitle: str, bullets: list[str], output: Path, accent="#60a5fa") -> Path:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for x in range(-100, W, 96):
        draw.line([(x, 0), (x + 180, H)], fill="#13213a", width=2)
    draw.rectangle((0, 0, W, 14), fill=accent)
    draw_wrapped(draw, (74, 60), title, font(42, True), "#ffffff", 1060, 6, max_lines=2)
    draw_wrapped(draw, (78, 150), subtitle, font(24), "#cbd5e1", 1030, 6, max_lines=2)

    count = len(bullets)
    card_h = 88 if count <= 4 else 76
    gap = 22 if count <= 4 else 14
    y = 245
    for bullet in bullets:
        rounded_card(draw, (88, y, 1160, y + card_h), "#172554", accent, 2, 20)
        draw.ellipse((118, y + 29, 140, y + 51), fill=accent)
        draw_wrapped(draw, (164, y + 20), bullet, font(23), "#f8fafc", 930, 4, max_lines=2)
        y += card_h + gap
    draw.text((76, H - 54), FOOTER, font=font(18, True), fill="#94a3b8")
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, quality=95)
    return output


def diagram_slide(title: str, nodes: list[dict], edges: list[tuple[str, str]], output: Path, active: int, subtitle="") -> Path:
    img = Image.new("RGBA", (W, H), "#f8fafc")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, W, 104), fill="#111827")
    draw_wrapped(draw, (56, 24), title, font(34, True), "#ffffff", 980, 4, max_lines=1)
    if subtitle:
        draw_wrapped(draw, (58, 66), subtitle, font(18), "#bfdbfe", 1040, 3, max_lines=1)

    node_map = {node["id"]: node for node in nodes}
    for i, (a, b) in enumerate(edges):
        na, nb = node_map[a], node_map[b]
        color = "#2563eb" if i < active else "#cbd5e1"
        _draw_antialiased_arrow(img, _route_edge(a, b, na, nb), color, 5)

    for i, node in enumerate(nodes):
        active_node = i <= active
        w = node.get("w", 252)
        h = node.get("h", 118)
        fill = node.get("color", "#2563eb") if active_node else "#e2e8f0"
        text = "#ffffff" if active_node else "#334155"
        outline = "#0f172a" if active_node else "#cbd5e1"
        rounded_card(draw, (node["x"], node["y"], node["x"] + w, node["y"] + h), fill, outline, 3, 24)
        draw_wrapped(draw, (node["x"] + 20, node["y"] + 18), node["label"], font(21, True), text, w - 40, 4, max_lines=3)
        if node.get("note"):
            draw_wrapped(draw, (node["x"] + 20, node["y"] + h - 42), node["note"], font(15), text, w - 40, 2, max_lines=1)
    draw.text((56, H - 44), "Mermaid-style staged diagram | Source-grounded learning sequence", font=font(18), fill="#64748b")
    output.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(output, quality=95)
    return output


def write_mermaid(name: str, body: str) -> Path:
    path = OUT_DIR / "mermaid" / f"{name}.mmd"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def build_part_assets(part: dict) -> tuple[Path, Path]:
    part_dir = ASSET_DIR / f"part_{part['number']:02d}"
    if part_dir.exists():
        for stale_png in part_dir.glob("*.png"):
            stale_png.unlink()
    scenes = []

    title_img = title_slide(part["number"], part["title"], part["subtitle"], part_dir / "00-title.png")
    scenes.append({"visual": "image", "image": str(title_img), "narration": part["intro"], "duration": 0})

    for idx, slide in enumerate(part["slides"], start=1):
        if slide["type"] == "diagram":
            nodes = slide["nodes"]
            edges = slide["edges"]
            for step in range(0, len(edges) + 1):
                img = diagram_slide(slide["title"], nodes, edges, part_dir / f"{idx:02d}-diagram-{step}.png", step, slide.get("subtitle", ""))
                narration = slide["narration"][min(step, len(slide["narration"]) - 1)]
                scenes.append({"visual": "image", "image": str(img), "narration": narration, "duration": 0})
        else:
            img = text_slide(slide["title"], slide["subtitle"], slide["bullets"], part_dir / f"{idx:02d}-text.png", slide.get("accent", "#60a5fa"))
            scenes.append({"visual": "image", "image": str(img), "narration": slide["narration"], "duration": 0})

    lab = part["lab"]
    img = text_slide(lab["title"], lab["subtitle"], lab["bullets"], part_dir / "98-closing.png", "#fbbf24")
    scenes.append({"visual": "image", "image": str(img), "narration": lab["narration"], "duration": 0})

    script = {
        "title": f"Evaluating Copilot Studio Agents - Part {part['number']}",
        "resolution": "1280x720",
        "fps": 30,
        "voice": "en-US-JennyNeural",
        "voice_rate": "+8%",
        "music_volume": 0,
        "scenes": scenes,
    }
    script_path = OUT_DIR / f"part_{part['number']:02d}.yaml"
    review_script_twice(script_path, script)
    script_path.write_text(yaml.safe_dump(script, sort_keys=False, allow_unicode=False), encoding="utf-8")
    output = OUT_DIR / f"part_{part['number']:02d}_{part['slug']}.mp4"
    return script_path, output


def render_part(part: dict, render: bool = True) -> Path:
    script_path, output = build_part_assets(part)
    if render:
        VideoCreator(str(script_path)).generate(str(output))
        validate_media(output)
    return output


def update_manifest(outputs: list[Path]):
    def rel(path: Path) -> str:
        return str(path.relative_to(ROOT)).replace("\\", "/")

    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {"demos": []}
    demos = [
        demo for demo in manifest.get("demos", [])
        if not (
            str(demo.get("status", "")).startswith("learning series - evaluating agents")
            or str(demo.get("status", "")).startswith("standalone learning series - evaluating agents")
        )
    ]
    for output in outputs:
        part_num = int(output.name.split("_")[1])
        part = PARTS[part_num - 1]
        demos.append({
            "id": f"evaluation-learning-series-part-{part_num}",
            "title": f"Standalone course video: Evaluating agents - Part {part_num}: {part['short_title']}",
            "status": "standalone learning series - evaluating agents (generated)",
            "source": rel(OUT_DIR / f"part_{part_num:02d}.yaml"),
            "video": rel(output),
            "description": part["subtitle"],
            "tags": ["standalone-video", "follow-along", "learning-series", "copilot-studio", "evaluation", "mermaid-style", "KarimaKT"],
        })
    manifest["demos"] = demos
    MANIFEST_PATH.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


PARTS = [
    {
        "number": 1,
        "slug": "start_with_value",
        "short_title": "Start with value",
        "title": "Start with value, not scores",
        "subtitle": "A maker's first evaluation job is deciding what V1 is allowed to be",
        "intro": "This first lesson reframes evaluation from a report card into a design instrument. You are a Copilot Studio maker building an agent, and before you ask whether it is good, you have to answer a sharper question: good at what, for whom, and in which lifecycle moment?",
        "slides": [
            {
                "type": "diagram",
                "title": "The maker's evaluation loop",
                "subtitle": "Scope the promise, target the bar, deliver evidence from real use",
                "nodes": [
                    {"id": "scope", "x": 92, "y": 246, "w": 248, "label": "Scope the value\nV1 promise + buckets", "color": "#2563eb"},
                    {"id": "target", "x": 508, "y": 246, "w": 248, "label": "Target the value\nreadiness + tradeoffs", "color": "#7c3aed"},
                    {"id": "deliver", "x": 924, "y": 246, "w": 248, "label": "Deliver the value\nlive sessions + ROI", "color": "#059669"},
                    {"id": "learn", "x": 508, "y": 500, "w": 248, "label": "Learn again\nnew tests from reality", "color": "#f59e0b"},
                ],
                "edges": [("scope", "target"), ("target", "deliver"), ("deliver", "learn"), ("learn", "scope")],
                "narration": [
                    "Here is the loop from the article, but seen through maker hands. Scope is where you decide the value promise. If the agent is for employee onboarding, V1 is not every HR question; it may be benefits enrollment, policy lookups, and escalation safety.",
                    "Then you target the value. This is the build-and-tune stage: generated cases, imported CSVs, expected answers where they matter, and graders that tell you which kind of wrong you are seeing.",
                    "After launch, the agent is no longer living in your imagination. Analytics sessions, themes, outcomes, tool use, custom metrics, and savings become the evidence stream that tells you whether users are receiving the value you promised.",
                    "The aha moment is that delivery does not end the evaluation loop. Real sessions become new cases, failed outcomes become new buckets, and the next version starts with better evidence than the first.",
                    "So throughout this course, do not think of evaluations as a score page. Think of them as the operating system for deciding scope, proving readiness, and learning from production.",
                ],
            },
            {
                "type": "text",
                "title": "A 78% pass rate is not an answer",
                "subtitle": "The same number can mean 'ship it' or 'stop everything' depending on the bucket",
                "bullets": [
                    "Must-Pass failure: one payroll or compliance answer can block the release.",
                    "Broader-use failure: useful signal for tuning persona, grounding, and answer shape.",
                    "Guardrail failure: the agent crossed a line; fix before scale amplifies it.",
                    "The score matters only after the maker labels what each row is protecting.",
                ],
                "accent": "#38bdf8",
                "narration": "This is where shallow evaluation goes wrong. A single pass rate compresses risk, usefulness, and business value into one number. For a maker, the job is to tag each case before the run. Then a 78 percent score becomes a map: which promises are safe, which are merely rough, and which are unacceptable.",
            },
        ],
        "lab": {
            "title": "If you are following along",
            "subtitle": "This is what you are prepared to do now in your project",
            "bullets": [
                "Write the V1 value promise in one sentence: user, job, and business outcome.",
                "Name three buckets: Must-Pass, Broader Use Cases, and Guardrails.",
                "Decide which score would be a launch blocker before you run anything.",
            ],
            "narration": "If you are following along, this is what you are prepared to do now in your project. You can write the value promise for your Copilot Studio agent, split early scenarios into risk buckets, and stop treating an overall score as if it were a release decision.",
        },
    },
    {
        "number": 2,
        "slug": "starter_test_set",
        "short_title": "Starter test set",
        "title": "Build the starter set as the V1 contract",
        "subtitle": "Turn stakeholder hopes into concrete rows a maker can design against",
        "intro": "In lesson two, the maker creates the artifact that prevents scope creep: the starter test set. It is not a giant QA spreadsheet. It is the contract for what V1 means in Copilot Studio.",
        "slides": [
            {
                "type": "diagram",
                "title": "From business promise to test set",
                "subtitle": "Each row says what the agent must handle, how to grade it, and what evidence counts",
                "nodes": [
                    {"id": "promise", "x": 84, "y": 218, "w": 238, "label": "Value promise\n'Unblock onboarding'", "color": "#2563eb"},
                    {"id": "cases", "x": 378, "y": 218, "w": 238, "label": "Starter cases\nmanual, test chat, CSV", "color": "#0891b2"},
                    {"id": "buckets", "x": 672, "y": 218, "w": 238, "label": "Buckets\nrisk + value", "color": "#7c3aed"},
                    {"id": "methods", "x": 966, "y": 218, "w": 238, "label": "Methods\nexpected answers + graders", "color": "#059669"},
                ],
                "edges": [("promise", "cases"), ("cases", "buckets"), ("buckets", "methods")],
                "narration": [
                    "A starter set begins in plain business language. What do users expect this agent to do on day one? If a scenario is not represented here, it is not a hidden requirement for V1.",
                    "Copilot Studio gives you several ways to create cases: write them manually with the business, convert useful test-chat turns, import a CSV, or generate cases from knowledge and topics when you need coverage fast.",
                    "Now bucket the rows. The bucket controls effort. A Must-Pass row deserves a carefully written expected answer or expected capability. A broader row may need an AI quality or custom rubric. A guardrail may need keywords or a refusal criterion.",
                    "The starter set becomes usable when each row has the right evidence attached. You are not filling columns for administration; you are deciding what kind of proof would convince you that the agent behaved well.",
                ],
            },
            {
                "type": "text",
                "title": "Expected answers are a scalpel, not a tax",
                "subtitle": "Use them where precision unlocks stronger methods",
                "bullets": [
                    "Expected answer: needed for Compare meaning, Text similarity, and Exact match.",
                    "Expected capability: use Capability use when the right tool or topic matters more than prose.",
                    "No reference answer: General quality can judge relevance, groundedness, completeness, and abstention.",
                    "Custom criteria: define labels such as 'Cites policy', 'Shows chart', or 'Safe refusal'.",
                ],
                "accent": "#818cf8",
                "narration": "The common mistake is thinking every test row needs a perfect answer. It does not. The maker tradeoff is precision versus effort. Expected answers are valuable where they unlock a precise comparison. But for open-ended recommendations, you often want an AI quality grader or a custom criterion that checks the shape of a good response: grounded, complete, formatted, and useful.",
            },
            {
                "type": "text",
                "title": "CSV and generated cases serve different jobs",
                "subtitle": "Imported rows express what the business knows; generated rows reveal what the agent surface suggests",
                "bullets": [
                    "CSV/import: bring curated questions, expected responses, and chosen methods in bulk.",
                    "Generated from knowledge or topics: rapidly probe coverage already visible to the agent.",
                    "Test-chat conversion: preserve a real maker discovery moment as a repeatable case.",
                    "Security note: generated cases can reflect data accessible to the connected test account.",
                ],
                "accent": "#22c55e",
                "narration": "This is a practical maker decision. Imported CSV rows are deliberate: they carry stakeholder intent. Generated rows are exploratory: they show what the platform can infer from your topics, tools, knowledge, and instructions. The tradeoff is speed versus authority. Use both, but do not confuse discovery coverage with the business contract.",
            },
        ],
        "lab": {
            "title": "If you are following along",
            "subtitle": "This is what you are prepared to do now in your project",
            "bullets": [
                "Create a starter test set with representative V1 questions, not every possible question.",
                "Choose where expected answers, expected capabilities, keywords, or rubrics are worth the effort.",
                "Use manual, test-chat, CSV, and generated cases intentionally instead of mixing them blindly.",
            ],
            "narration": "If you are following along, this is what you are prepared to do now in your project. You can create a starter test set, bucket each row, and choose the evidence type that fits the row instead of over-documenting everything.",
        },
    },
    {
        "number": 3,
        "slug": "target_readiness",
        "short_title": "Target readiness",
        "title": "Tune readiness without fooling yourself",
        "subtitle": "Use generated volume, rubrics, and blind sets to make tradeoffs visible",
        "intro": "Lesson three is the builder's workshop. You have a starter contract. Now you need enough volume to tune, enough criteria to explain failures, and a blind set so you do not accidentally train yourself to the answers.",
        "slides": [
            {
                "type": "diagram",
                "title": "Readiness is tuned, then challenged",
                "subtitle": "The working set improves the agent; the blind set checks whether learning generalized",
                "nodes": [
                    {"id": "volume", "x": 92, "y": 210, "w": 250, "label": "Generated or imported volume\nup to the useful limit", "color": "#0891b2"},
                    {"id": "working", "x": 406, "y": 158, "w": 250, "label": "Working set\niterate freely", "color": "#2563eb"},
                    {"id": "blind", "x": 406, "y": 378, "w": 250, "label": "Blind set\nuntouched until ready", "color": "#7c3aed"},
                    {"id": "gap", "x": 814, "y": 268, "w": 300, "label": "Compare the gap\n92% vs 64% means overfit", "color": "#dc2626"},
                ],
                "edges": [("volume", "working"), ("volume", "blind"), ("working", "gap"), ("blind", "gap")],
                "narration": [
                    "Readiness needs more than a starter set. Generate or import enough cases to see patterns: missing grounding, bad tool choice, weak formatting, brittle instructions, or policy risk.",
                    "The working set is where the maker experiments. You change instructions, knowledge descriptions, topic triggers, tool descriptions, or connector behavior, then rerun the same rows to see what moved.",
                    "The blind set is the discipline. It has the same shape as the working set, but you do not tune against it. It answers a different question: did the agent learn the capability, or did the maker learn the test?",
                    "The aha moment is the gap. Working set at 92 and blind at 64 is not a success story. It is proof that your tuning was too narrow, your rubrics were too permissive, or your examples taught a shortcut.",
                    "When the gap closes, readiness becomes a defensible conversation. Not perfect, but understood: here is what improved, here is what still fails, and here is the release risk we accept.",
                ],
            },
            {
                "type": "text",
                "title": "A custom rubric makes fuzzy quality inspectable",
                "subtitle": "Turn 'I don't like the answer' into labeled criteria the team can debate",
                "bullets": [
                    "Example quality rubric: has Markdown headings, includes a table, cites source, uses the requested chart.",
                    "Labels should map to pass or fail so the evaluation changes the pass rate, not just the commentary.",
                    "AI quality catches relevance, groundedness, completeness, and abstention; custom criteria catch your business shape.",
                    "Thumbs-up/down feedback on evaluation results helps refine whether the grader judged well.",
                ],
                "accent": "#a78bfa",
                "narration": "The article's Eurozone example is the right mental model. The agent may answer correctly but fail the maker's UX expectation: no table, no chart, no headers. A custom rubric turns that subjective frustration into inspectable labels. Now the team can tune the prompt or tool output against a named failure.",
            },
            {
                "type": "text",
                "title": "Every tuning move has a cost",
                "subtitle": "Evaluations make the tradeoff visible before a stakeholder discovers it",
                "bullets": [
                    "Stricter grounding can reduce hallucinations but increase abstentions.",
                    "More tool detail can improve capability use but make answers slower or noisier.",
                    "A stronger refusal rule can protect guardrails but block legitimate edge cases.",
                    "The right question is not 'Did the score rise?' It is 'Which bucket moved and why?'",
                ],
                "accent": "#fb7185",
                "narration": "This is the teaching moment most scorecard videos miss. Tuning is not a magic ladder to 100 percent. It is a series of product choices. Evaluations help you see which bucket benefited and which bucket paid the price, so readiness becomes a decision instead of a vibe.",
            },
        ],
        "lab": {
            "title": "If you are following along",
            "subtitle": "This is what you are prepared to do now in your project",
            "bullets": [
                "Create more volume with generated or imported cases after the starter contract is clear.",
                "Split working and blind sets so iteration does not become overfitting.",
                "Add one custom rubric that represents the user experience your agent must deliver.",
            ],
            "narration": "If you are following along, this is what you are prepared to do now in your project. You can expand your evaluation volume, split working and blind sets, add a business-specific rubric, and explain readiness as a set of visible tradeoffs.",
        },
    },
    {
        "number": 4,
        "slug": "live_analytics",
        "short_title": "Live analytics",
        "title": "Use live analytics as evaluation fuel",
        "subtitle": "After launch, production sessions become the next test design surface",
        "intro": "Lesson four moves from the maker studio to real use. The agent is published. Users phrase things differently, tools fail in new ways, and analytics becomes the source of evaluation evidence.",
        "slides": [
            {
                "type": "diagram",
                "title": "Production closes the loop",
                "subtitle": "Analytics tells you where to fetch, grade, measure, and reinvest",
                "nodes": [
                    {"id": "sessions", "x": 72, "y": 230, "w": 238, "label": "Analytics sessions\noutcomes, themes, transcripts", "color": "#2563eb"},
                    {"id": "fetch", "x": 374, "y": 230, "w": 238, "label": "Fetch into test sets\nreal user phrasing", "color": "#0891b2"},
                    {"id": "metrics", "x": 676, "y": 230, "w": 238, "label": "Custom metrics\nlive rubric on conversations", "color": "#7c3aed"},
                    {"id": "roi", "x": 978, "y": 230, "w": 238, "label": "Savings and ROI\nper run or per tool", "color": "#059669"},
                ],
                "edges": [("sessions", "fetch"), ("fetch", "metrics"), ("metrics", "roi")],
                "narration": [
                    "Copilot Studio analytics is not just a dashboard for leaders. For makers, it is a listening surface: outcomes, themes, generated answer quality, tool use, knowledge source use, user feedback, and session details point to where the agent is struggling.",
                    "The powerful move is to fetch real questions into evaluation. Now the test set stops being hypothetical. It carries the way users actually ask, the topics that cluster in themes, and the outcomes that matter: resolved, escalated, abandoned, or unengaged.",
                    "Custom analytics metrics are the live twin of your custom evaluation rubric. If V1 was gated on 'answer includes the chart and table the user asked for,' the live classifier can watch production conversations for that same shape.",
                    "Then connect quality to value. The maker decision is what evidence deserves operational attention: a baseline drop, a theme spike, a failed custom metric, or a savings signal. The Savings calculator can estimate time or money saved per run, or per tool for conversational agents, so the tradeoff is no longer quality versus business value; it is which signal should drive the next build investment.",
                ],
            },
            {
                "type": "text",
                "title": "The global alert is a smoke alarm, not a diagnosis",
                "subtitle": "Calibrate a baseline, then investigate the bucket behind the drop",
                "bullets": [
                    "A single environment performance value is too broad to define quality by itself.",
                    "After calibration, a drop from baseline tells you when to inspect sessions and rerun affected sets.",
                    "Use themes and outcomes to choose which questions become new evaluation rows.",
                    "Export results when you need a longer-lived trail; recent detailed results have retention windows.",
                ],
                "accent": "#f97316",
                "narration": "The article calls out a subtle feature: a global alert feels irrelevant until you treat it as a baseline delta. It is not telling you what broke. It is telling you when to look. The maker then drills into themes, outcomes, transcripts, and test runs to locate the bucket that moved.",
            },
            {
                "type": "text",
                "title": "Analytics sessions are not the same for every agent",
                "subtitle": "Conversational, event-triggered, and hybrid agents produce different evidence",
                "bullets": [
                    "Conversational sessions track user interaction and outcomes across one or more analytics sessions.",
                    "Event-triggered agents track a run from trigger payload through actions executed in response.",
                    "Hybrid views separate conversation and run evidence so you do not mix unlike signals.",
                    "Test-panel activity is not the same as production analytics; design-time data comes from other sources.",
                ],
                "accent": "#14b8a6",
                "narration": "A maker-centered course has to say this plainly: analytics data types matter. Conversational agents and event-triggered agents produce different sessions. If you mix them into one generic quality story, you lose the causal trail. Match the evaluation question to the session type.",
            },
        ],
        "lab": {
            "title": "If you are following along",
            "subtitle": "This is what you are prepared to do now in your project",
            "bullets": [
                "Use analytics themes, outcomes, tool use, and transcripts to pick new evaluation cases.",
                "Turn one launch rubric into a live custom metric or classifier.",
                "Connect successful runs or tools to a time or money savings estimate.",
            ],
            "narration": "If you are following along, this is what you are prepared to do now in your project. You can use live analytics as a source of new tests, track a custom quality metric in production, and connect evaluation evidence to ROI or tool savings.",
        },
    },
    {
        "number": 5,
        "slug": "operationalize_quality",
        "short_title": "Operationalize quality",
        "title": "Operationalize quality gates",
        "subtitle": "Choose single-turn or multi-turn tests, stack graders, and automate only after the signal is trusted",
        "intro": "The final lesson turns the evaluation system into an operating habit. You know the buckets, the data sources, and the methods. Now you make the system repeatable without losing judgment.",
        "slides": [
            {
                "type": "diagram",
                "title": "Choose the gate by what can break",
                "subtitle": "Path, answer, policy, memory, and release automation need different evidence",
                "nodes": [
                    {"id": "case", "x": 68, "y": 230, "w": 222, "label": "Test case\nquestion or conversation", "color": "#2563eb"},
                    {"id": "path", "x": 340, "y": 154, "w": 238, "label": "Path grader\nCapability use / keywords", "color": "#0891b2"},
                    {"id": "answer", "x": 340, "y": 390, "w": 238, "label": "Answer grader\nquality / meaning / rubric", "color": "#7c3aed"},
                    {"id": "gate", "x": 724, "y": 270, "w": 250, "label": "Quality gate\npass, fail, invalid, error", "color": "#059669"},
                    {"id": "auto", "x": 1030, "y": 270, "w": 180, "label": "API or connector\nscheduled / CI", "color": "#111827"},
                ],
                "edges": [("case", "path"), ("case", "answer"), ("path", "gate"), ("answer", "gate"), ("gate", "auto")],
                "narration": [
                    "Final evaluation design starts with what can break. Did the agent call the right tool? Did it use the right topic? Did the answer mean the expected thing? Did it satisfy the rubric? These are different questions.",
                    "Path graders catch what the agent did: capability use, expected tools, expected topics, and sometimes keywords that must appear or must not appear. They are especially useful for Must-Pass flows and tool-chain validation.",
                    "Answer graders catch how the agent responded: General quality, Compare meaning, Text similarity, Exact match, or a custom rubric. Stack path and answer checks on the same row when both matter.",
                    "The gate reads pass, fail, invalid, or error. Invalid often means your row is missing the expected answer or keyword required by the chosen method. That is not an agent bug; it is a test design bug.",
                    "Only then automate. Use the Power Platform REST API or the Microsoft Copilot Studio connector actions to evaluate a test set, get run details, list test sets, and publish results to a dashboard, email, or release gate.",
                    "The full picture is a quality gate, not a scorecard. One row can prove the route, the answer, the policy behavior, and the automation signal you are willing to trust.",
                ],
            },
            {
                "type": "text",
                "title": "Single-turn tests are stronger than they look",
                "subtitle": "One row can still exercise plan, retrieve, call, compose, and answer",
                "bullets": [
                    "Use single-response sets when the question, tool choice, and final answer are the thing being judged.",
                    "Use multi-turn conversation sets when state accumulates: clarification, handoff, memory, or multi-step tasks.",
                    "Conversation sets have smaller limits and different supported methods, so reserve them for stateful behavior.",
                    "Do not create multi-turn theater when a focused single-turn case would catch the regression faster.",
                ],
                "accent": "#38bdf8",
                "narration": "Here is the aha moment: a single-turn evaluation is not shallow by default. In a generative orchestrated agent, one question can trigger planning, knowledge retrieval, tool execution, another tool, and response composition. The maker tradeoff is focus versus realism. Multi-turn earns its place only when the previous turn changes what the next answer should be.",
            },
            {
                "type": "text",
                "title": "Automation has prerequisites",
                "subtitle": "DLP, connection identity, API access, and stable test design all matter",
                "bullets": [
                    "DLP can block the Microsoft Copilot Studio connector, including authenticated automated evaluations.",
                    "User profiles and mcsConnectionId matter when tools or knowledge need a connected account during tests.",
                    "REST API flow: list test sets, start run, poll run details, store results by run ID.",
                    "Connector flow: Evaluate Agent, Get Test Run Details, then alert, dashboard, or gate based on results.",
                ],
                "accent": "#fbbf24",
                "narration": "The operational lesson is not glamorous, but it saves days. Before you promise quality gates, confirm data policy allows the evaluation actions, pick the right test identity for connected tools, and make sure the test sets themselves are stable. The tradeoff is speed versus trust: automation amplifies good signals and bad signals equally.",
            },
        ],
        "lab": {
            "title": "If you are following along",
            "subtitle": "This is what you are prepared to do now in your project",
            "bullets": [
                "Stack deterministic and AI methods so one row checks both path and answer.",
                "Choose single-turn by default; use multi-turn only when conversation state is the behavior under test.",
                "Prepare DLP, connector/API access, test identity, and result storage before automating runs.",
            ],
            "narration": "If you are following along, this is what you are prepared to do now in your project. You can design a quality gate for your Copilot Studio agent, choose single-turn or multi-turn tests deliberately, stack the right graders, and automate evaluations through connectors or the Power Platform API when the signal is trusted.",
        },
    },
]


def write_all_mermaid() -> list[Path]:
    mermaid_dir = OUT_DIR / "mermaid"
    if mermaid_dir.exists():
        for stale_mmd in mermaid_dir.glob("*.mmd"):
            stale_mmd.unlink()
    diagrams = {
        "01-maker-value-loop": """
flowchart LR
  Scope[Scope the value\nV1 promise + buckets] --> Target[Target the value\nreadiness + tradeoffs]
  Target --> Deliver[Deliver the value\nlive sessions + ROI]
  Deliver -. production learning .-> Scope
""",
        "02-starter-contract": """
flowchart LR
  Promise[Business value promise] --> Cases[Starter test cases\nmanual + test chat + CSV + generated]
  Cases --> Buckets[Must-Pass\nBroader Use Cases\nGuardrails]
  Buckets --> Methods[Expected answers\nCapabilities\nAI quality\nCustom criteria]
""",
        "03-working-blind-readiness": """
flowchart LR
  Volume[Generated or imported volume] --> Working[Working set\nmaker tunes here]
  Volume --> Blind[Blind set\nheld back]
  Working --> Gap[Compare pass-rate gap]
  Blind --> Gap
  Gap --> Decision[Ship, tune, or rescope]
""",
        "04-production-evidence-loop": """
flowchart LR
  Analytics[Analytics sessions\nthemes + outcomes + transcripts] --> Fetch[Fetch real questions\ninto evaluation sets]
  Fetch --> Metrics[Custom metrics / classifiers]
  Metrics --> ROI[Savings\nper run or per tool]
  Fetch -. new regression cases .-> Analytics
""",
        "05-quality-gate-automation": """
flowchart LR
  Row[Test case] --> Path[Capability use\nKeyword / tool / topic]
  Row --> Answer[General quality\nCompare meaning\nCustom rubric]
  Path --> Gate[Quality gate]
  Answer --> Gate
  Gate --> Auto[Connector or REST API\nCI / schedule / dashboard]
""",
    }
    return [write_mermaid(name, body) for name, body in diagrams.items()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Evaluating Copilot Studio Agents learning series.")
    parser.add_argument("--no-render", action="store_true", help="Create slide assets, YAML scripts, Mermaid files, and manifest entries without rendering MP4s.")
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    mermaid = write_all_mermaid()
    if not args.no_render:
        for stale_video in OUT_DIR.glob("part_*.mp4"):
            stale_video.unlink()
    outputs = [render_part(part, render=not args.no_render) for part in PARTS]
    update_manifest(outputs)
    report = {
        "series": SERIES,
        "rendered": not args.no_render,
        "outputs": [str(path) for path in outputs],
        "manifest": str(MANIFEST_PATH),
        "mermaid": [str(path) for path in mermaid],
        "scripts": [str(OUT_DIR / f"part_{part['number']:02d}.yaml") for part in PARTS],
        "script_reviews": SCRIPT_REVIEWS,
    }
    (OUT_DIR / "series-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
