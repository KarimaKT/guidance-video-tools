# CAT Video Tools skills

These are portable Clawpilot / Agency Copilot instructions that help users prepare better inputs before using the app.

The app remains the deterministic renderer and media processor. The skills are planning and drafting companions: they generate YAML, clip plans, sanitizer notes, and learning-video briefs that the user reviews and brings back into the app.

## Skill index

| Skill | Use before | Output to bring back |
|---|---|---|
| `/meeting-sanitizer-plan` | Meeting Sanitizer | Keep speakers, candidate cut ranges, masking checks, title/end-card text, review checklist |
| `/clip-extractor-plan` | Clip Extractor | Paste-ready clip ranges, viewer-facing titles, categories, review notes |
| `/demo-video-draft` | Demo Video Creator | Demo Video Creator YAML with screenshot/video placeholders |
| `/technical-learning-video` | Technical Explainer Studio | Topic brief, source notes, storyboard, learning arc guidance |
| `video_app_user.md` | Operating CAT Video Tools | Review-before-render usage guidance |
| `video_app_maker.md` | Building similar tools | Product and engineering guidance for human-reviewed video apps |

## How to use

1. Copy or install the skill in Clawpilot / Agency Copilot.
2. Run the skill with your topic, recording notes, transcript excerpts, source links, or audience.
3. Review the generated plan or YAML.
4. Bring the reviewed output back into CAT Video Tools.
5. Render only after the app audit/preview/review step is complete.

## Package decision

Do not turn these prompt skills into Python or npm packages yet. They are intentionally lightweight, editable instructions.

Package candidates are the deterministic engines:

- `sanitizer/media_pipeline.py`
- `sanitizer/clip_extractor.py`
- `sanitizer/meeting_editor.py`
- `creator/video_creator.py`
- `creator/web_walkthrough.py`

Those should become a Python package only after the public API is stable and the generated/demo artifacts are curated out of source control.
