# /demo-video-draft

Generate a viewer-facing CAT Video Tools Demo Video Creator YAML draft from a topic, scenario, audience, and optional capture notes.

## Use when

You have a rough demo idea and want Clawpilot or Agency Copilot to draft the YAML before you upload it into Demo Video Creator.

## Instructions

You are generating a draft YAML script for CAT Video Tools: Demo Video Creator.

I will give you a topic, product, feature, or scenario. Create a viewer-facing product demo script, not an internal task list.

The output must be valid YAML for the existing Video Creator format.

Quality rules:
- Start with "Introducing [product/feature]..."
- Name what was built or what is being demonstrated.
- Explain who it helps.
- Explain the real problem or scenario before UI mechanics.
- Keep the walkthrough short.
- Use 1-2 UI actions per section.
- Do not use timestamp narration like "at 4 seconds."
- Do not expose implementation steps, skill todos, or production workflow.
- Do not invent product capabilities that were not provided.
- Make the narration substantive and user-centered.
- Use clean slide scenes plus placeholder image/video scenes where screenshots or walkthrough clips should go.
- Mark any screenshot/video placeholders clearly so they can be replaced before rendering.
- Include 5-7 scenes maximum.
- Use professional colors and `animation: "none"`.

Return only YAML. No Markdown fence. No explanation.

## YAML shape

```yaml
title: "[Demo title]"
resolution: "1280x720"
fps: 30
voice: "en-US-JennyNeural"
voice_rate: "+8%"
music_volume: 0

scenes:
  - title: "Introducing [Product or Feature]"
    subtitle: "[What it does and who it helps]"
    visual: "slide"
    narration: >
      Introducing [Product or Feature]. We built this for [audience] who need
      to [job/problem]. It helps them [outcome 1], [outcome 2], and [outcome 3]
      without [pain/friction].
    bullets:
      - "[Outcome 1]"
      - "[Outcome 2]"
      - "[Outcome 3]"
    background: "#0f172a"
    text_color: "#ffffff"
    accent_color: "#93c5fd"
    animation: "none"
```

