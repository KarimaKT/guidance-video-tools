# /clip-extractor-plan

Generate Clip Extractor planning input: timestamp ranges, titles, categories, rationale, and review notes for short clips.

## Use when

You have a webinar, transcript notes, or rough moments and want a paste-ready clip plan before rendering clips.

## Instructions

Turn rough notes, transcript excerpts, or a webinar outline into intentional clip ranges with viewer-facing titles and categories.

Use whatever is provided:
- Source video/topic
- Transcript excerpts or timestamps
- Desired audience
- Desired number of clips
- Topics to emphasize
- Publishing channel or tone

If exact timestamps are missing, produce a planning table and mark ranges as `timestamp needed` instead of inventing times.

Return two sections.

## Paste-ready clip ranges

Use this exact format when timestamps are known:

```text
6:09 - 7:17 | Agents Are Not Apps | AI agents
22:51 - 26:20 | Natural Language to Query | Structured data
```

## Review notes

For each clip include:
- Why this moment is worth clipping
- What the opening context should establish
- Whether the title is user-facing enough
- Any privacy/quality concern to check before rendering

Quality rules:
- Prefer fewer, stronger clips over many weak clips.
- Titles should be viewer-facing, not internal labels.
- Do not invent timestamps.
- Avoid arbitrary duration rules.
- Make categories useful for grouping in the Created Video Library.

