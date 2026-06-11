# Test and demo assets

This folder is the curated test/demo hub for CAT Video Tools.

Keep it lean:

1. Include only assets needed to demonstrate or validate a workflow.
2. Prefer small representative outputs, thumbnails, manifests, configs, or generation scripts.
3. Do not copy large source recordings or intermediate outputs unless they are essential.
4. Keep private transcripts and recordings out of source control by default.

The Streamlit app reads `demo_manifest.yaml` for the Test Gallery. Shared/release demos should use relative paths and sanitized assets. Keep local absolute paths in private, untracked manifests only.
