# Portable skill: building human-reviewed video tools

Use this guidance when building apps similar to Guidance Video Tools.

## Principles

1. Make AI decisions editable before rendering.
2. Keep media pipelines deterministic and auditable.
3. Treat privacy and speaker identity as product requirements, not post-processing.
4. Use curated demo/test assets instead of copying every source or intermediate file.
5. Prefer manifests and project files over hidden UI state.
6. Do not present a render as done until stitching has been validated against expected duration.

## Recommended app structure

- A manifest-driven test/demo gallery with small representative examples.
- A project YAML or JSON file that captures source files, selected speakers, cuts, masks, title/end cards, and export settings.
- A dry-run or audit mode that explains every cut, mute, mask, and generated clip.
- A render layer shared by sanitizer, clip extraction, and creator workflows.
- Smoke tests that use synthetic media, plus a small curated gallery for human QA.
- A separate Demo Video Creator for short product demos and guided web tours.
- A separate Technical Explainer Studio for source-grounded teaching videos, misconceptions, learning arcs, and course-style content.

## Media pipeline lessons

- Avoid keyframe-only trimming for final cuts; use frame-accurate trim paths and re-encode when necessary.
- Normalize video dimensions, sample aspect ratio, audio sample rate, and channel layout across all segments before concatenation.
- Use filter-based concatenation for mixed slides, extracted clips, and embedded walkthrough/video scenes.
- Never ignore FFmpeg return codes; surface stderr with enough context to debug.
- Keep intermediate files in a unique temp folder and delete only generated temp folders.
- Validate output with ffprobe after render: duration, audio stream, video stream, and codec.
- Compare stitched output duration against the sum of input durations and fail loudly when it drifts.
- Include a regression test that stitches generated slides with an embedded video clip that has a different resolution, frame rate, and audio shape.

## Human review workflow

Show decisions in this order:

1. Transcript speakers and normalized names.
2. AI-proposed keep/cut ranges with reasons.
3. Manual include/exclude overrides.
4. Visual mask decisions.
5. Title/end-card settings.
6. Final render summary and output checks.
