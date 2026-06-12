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

## Natural-language prompt starters

### Meeting Sanitizer

```text
Use skills/meeting-sanitizer-plan.md. I have a recording and transcript to clean up.
Keep these speakers: [...]
Remove/mask these people or sections: [...]
Known timestamps/transcript notes: [...]
Create a review-first sanitizer plan and starter YAML. Do not invent timestamps.
```

### Clip Extractor

```text
Use skills/clip-extractor-plan.md. I need short publishable clips from a long recording.
Audience: [...]
Topics to emphasize: [...]
Transcript notes or rough timestamps: [...]
Return paste-ready ranges: MM:SS - MM:SS | title | category. Do not invent timestamps.
```

### Demo Video Creator

```text
Use skills/demo-video-draft.md. Create CAT Video Tools YAML for a product demo.
Product/feature: [...]
Audience: [...]
Problem and value: [...]
Assets/page URL/walkthrough notes: [...]
Return only valid YAML with placeholder media paths where needed.
```

### Technical Explainer Studio

```text
Use skills/technical-learning-video.md. Create a source-grounded learning video plan.
Topic: [...]
Audience: [...]
Misunderstanding to correct: [...]
Sources/assets: [...]
Produce a storyboard, narration intent, visual strategy, two-pass review, and QA checklist.
```

## Best prompting practices

- Give the viewer, purpose, and source material before asking for YAML.
- Use exact transcript speaker names and known timestamps when possible.
- Ask for `review_needed` instead of letting the assistant guess.
- Require viewer-facing titles and openings.
- Keep generated YAML reviewable: short scenes, clear assets, no hidden production tasks.
- Bring plans back into the app and render only after audit/preview.

## Package decision

Do not turn these prompt skills into Python or npm packages yet. They are intentionally lightweight, editable instructions.

Package candidates are the deterministic engines:

- `sanitizer/media_pipeline.py`
- `sanitizer/clip_extractor.py`
- `sanitizer/meeting_editor.py`
- `creator/video_creator.py`
- `creator/web_walkthrough.py`

Those should become a Python package only after the public API is stable and the generated/demo artifacts are curated out of source control.
