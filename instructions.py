# Edit Instructions & Templates
#
# An edit instruction file describes HOW to edit a specific meeting recording.
# A template provides reusable defaults for a type of meeting.
#
# Workflow:
#   1. Pick a template (or start from scratch)
#   2. Create an edit_instructions.yaml for your project
#   3. Run: python sanitize.py edit_instructions.yaml
#   4. Review the audit output
#   5. Tweak instructions and re-run until satisfied

import yaml
import copy
from pathlib import Path
from dataclasses import dataclass, field


TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class EditInstructions:
    """Parsed edit instructions ready for MeetingEditor."""
    video_path: str = ""
    vtt_path: str = ""
    keep_speakers: list = field(default_factory=list)
    segments: list = field(default_factory=list)          # [(start, end), ...]
    layout_overrides: dict = field(default_factory=dict)  # {seg_idx: [Rect, ...]}
    audio_enhance: bool = True
    crf: int = 22
    output_path: str = "output.mp4"
    # Customizable patterns
    admin_patterns: list = field(default_factory=list)
    reaction_patterns: list = field(default_factory=list)


def load_template(name: str) -> dict:
    """Load a template by name from the templates/ directory."""
    path = TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Template '{name}' not found. "
            f"Available: {', '.join(t.stem for t in TEMPLATES_DIR.glob('*.yaml'))}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def list_templates() -> list[dict]:
    """List all available templates."""
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        templates.append({
            "name": path.stem,
            "description": data.get("description", ""),
            "path": str(path),
        })
    return templates


def load_instructions(yaml_path: str) -> EditInstructions:
    """Load edit instructions from a YAML file, merging with template if specified."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Start with template defaults if specified
    config = {}
    template_name = raw.get("template")
    if template_name:
        config = load_template(template_name)

    # Merge project-specific values on top of template
    _deep_merge(config, raw)

    # Parse into EditInstructions
    instructions = EditInstructions()
    instructions.video_path = config.get("video", "")
    instructions.vtt_path = config.get("vtt", "")
    instructions.keep_speakers = config.get("keep_speakers", [])
    instructions.output_path = config.get("output", "output.mp4")
    instructions.crf = config.get("settings", {}).get("crf", 22)
    instructions.audio_enhance = config.get("settings", {}).get("audio_enhance", True)

    # Parse segments
    for seg in config.get("segments", []):
        if isinstance(seg, dict):
            instructions.segments.append((seg["start"], seg["end"]))
        elif isinstance(seg, (list, tuple)) and len(seg) >= 2:
            instructions.segments.append((seg[0], seg[1]))

    # Parse layout overrides
    for override in config.get("layout_overrides", []):
        seg_idx = override.get("segment")
        if seg_idx is not None:
            from meeting_editor import Rect
            rects = []
            for m in override.get("masks", []):
                rects.append(Rect(
                    x=m["x"], y=m["y"], w=m["w"], h=m["h"],
                    label=m.get("label", "")
                ))
            instructions.layout_overrides[seg_idx] = rects

    # Custom patterns (merge template + project)
    patterns = config.get("settings", {}).get("disturbance_detection", {})
    instructions.admin_patterns = patterns.get("admin_patterns", [])
    instructions.reaction_patterns = patterns.get("reaction_patterns", [])

    return instructions


def save_instructions_template(instructions: EditInstructions, output_path: str):
    """Save current instructions as a reusable YAML file."""
    data = {
        "video": instructions.video_path,
        "vtt": instructions.vtt_path,
        "keep_speakers": instructions.keep_speakers,
        "output": instructions.output_path,
        "settings": {
            "crf": instructions.crf,
            "audio_enhance": instructions.audio_enhance,
        },
    }

    if instructions.segments:
        data["segments"] = [
            {"start": s, "end": e, "note": f"Segment {i+1}"}
            for i, (s, e) in enumerate(instructions.segments)
        ]

    if instructions.layout_overrides:
        data["layout_overrides"] = []
        for seg_idx, rects in instructions.layout_overrides.items():
            data["layout_overrides"].append({
                "segment": seg_idx,
                "masks": [
                    {"x": r.x, "y": r.y, "w": r.w, "h": r.h, "label": r.label}
                    for r in rects
                ]
            })

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    print(f"  Saved instructions to: {output_path}")


def _deep_merge(base: dict, override: dict):
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
