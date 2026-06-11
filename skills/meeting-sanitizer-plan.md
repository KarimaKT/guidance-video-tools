# /meeting-sanitizer-plan

Generate review-first Meeting Sanitizer prep notes: keep speakers, candidate cut ranges, masking/verification notes, title/end cards, and QA checklist.

## Use when

You have a recording/transcript scenario and want a plan before uploading files into Meeting Sanitizer.

## Instructions

Turn rough recording notes, transcript excerpts, speaker names, or privacy concerns into sanitizer inputs the user can review and bring back to the app.

Use whatever is provided:
- Recording purpose or meeting title
- Transcript excerpt or speaker list
- Speakers to keep
- Speakers or sections to remove
- Known start/end ranges
- Privacy or masking concerns
- Desired title card and ending card

If details are missing, make reasonable assumptions and mark them as `review_needed`.

Return concise Markdown with:

1. **Keep speakers**
   - Names exactly as they should appear in the app.
2. **Candidate ranges**
   - `MM:SS - MM:SS | reason | confidence`
3. **Masking/verification notes**
   - What to verify visually and which timestamp to check first.
4. **Title and ending cards**
   - Suggested title/subtitle/end text.
5. **Review checklist**
   - What the user must inspect before rendering.

Quality rules:
- Keep human review central.
- Do not claim a range is safe unless grounded in provided transcript/details.
- Do not invent exact timestamps. If timestamps are unavailable, say `timestamp needed`.
- Avoid internal implementation language.
- Focus on safer sharing, presenter preservation, disturbance removal, masking, and final QA.

