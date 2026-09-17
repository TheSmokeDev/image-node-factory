---
description: Validate the Image Node Factory prompt-pack and render artifacts.
argument-hint: "(reads prompt pack, manifest, and optional render result)"
---

# Image Node QA

**Workflow ID**: $WORKFLOW_ID

## Contract

Validate the image workflow artifacts. This is an artifact QA pass, not a render
node. Do not call image generation, OpenAI APIs, CLI fallback scripts, or
external services.

Read:
- `$ARTIFACTS_DIR/image-node-preflight.json`
- `$ARTIFACTS_DIR/image-node-brief.json`
- `$ARTIFACTS_DIR/image-node-selection.json`
- `$ARTIFACTS_DIR/image-node-prompt-pack.md`
- `$ARTIFACTS_DIR/image-node-prompt-pack.json`
- `$ARTIFACTS_DIR/image-node-imagegen-packet.json`
- `$ARTIFACTS_DIR/images/manifest.json`
- Parallel render receipt if present: `$ARTIFACTS_DIR/image-node-render-receipt.json`
- Render stdout if present: `$render.output`
- Deterministic render geometry receipt if present: `$validate-render.output`

Write:
- `$ARTIFACTS_DIR/qa-report.md`

Then output ONLY the QA JSON described below.

## Checks

Selection checks:
- `template_id` is one of the library template ids.
- `category` and `discipline_card` are set and consistent with the mapping.
- `example_case_ids` is present and is an array of INTEGERS. The selection
  references library cases rather than pasting their prompt text.

Grounding checks (a citation must resolve, or must not be made):
- If the packet or prompt pack names `prompt_engine`, then `$ground.output.grounded`
  is `true` AND every cited `example_case_ids` entry appears in
  `$ground.output.resolved_case_ids`. A cited id that is unresolved is a FAIL.
- If `$ground.output.grounded` is `false`, the pack carries `self_authored: true`
  and carries NO `prompt_engine` and NO `example_case_ids`. Anything else is a FAIL.
- No `*.local.json` file is quoted, copied, or listed in the manifest or the
  publishable pack.

Prompt pack checks:
- Required artifacts exist and contain parseable JSON where expected.
- Concept count matches expected count.
- In a 6-to-10 option batch, concepts are materially different in composition,
  evidence focal point, framing, and type-image relationship. Cosmetic palette
  swaps or the same template repeated ten times are a FAIL.
- Every concept carries BOTH a `baked_prompt` and an `overlay_prompt`.
- Overlay concepts include a `copy` object and a text-free scene with a
  forbid-text clause and reserved empty space.
- Baked concepts quote `exact_text` verbatim when it was requested.
- Exact-text baked prompts require letter-perfect copy, no extra words, no
  duplicate text, explicit hierarchy/placement/contrast, and safe margins.
- Negative constraints include no watermark, no random logos, no garbled text,
  and no extra text beyond requested copy.
- No absolute local run paths, private system names, OpenAI API-key
  dependencies, or external render services appear in the public prompt pack.
- Public prompt-pack and packet JSON use relative artifact names. The QA report
  may include absolute local paths because it is a local run report.

Packet checks:
- `artifact_type` is `imagegen-workflow-packet`.
- `schema_version` is `1`.
- `render_disciplines` lists both `baked` and `overlay`.
- Packet includes the canonical node order: `classify-request`, `route-vertical`,
  `route-lighting-choice`, `collect-input-images`, `build-production-spec`,
  `qa-generated-image`, `execute-imagegen`.

Render checks:
- If manifest status is `prompt_pack_only`, this is a passing dry-run when the
  prompt pack and packet are valid.
- If manifest status is `blocked`, this is a passing local capability-gate test
  when `render-blocked.md` exists and no API fallback was attempted.
- If manifest status is `rendered`, image files must exist under
  `$ARTIFACTS_DIR/images/`, match the manifest count, and record which variant
  was rendered.
- A rendered batch must carry one coordinator receipt with per-job start/end,
  duration, output SHA-256, and Codex thread ownership when exposed. Duplicate
  output hashes or more than three simultaneous render slots are a FAIL.
- A batch of two or more concepts must include the deterministic review contact
  sheet named by the manifest.
- A rendered run must pass the deterministic `validate-render` geometry receipt.
- Rendered aspect ratio must match the intake ratio within the deterministic
  tolerance; a visually attractive wrong-ratio image is a FAIL, not a crop-ready
  candidate.
- For baked exact-text output, manually transcribe every visible character and
  compare against `exact_text`. Missing punctuation, duplicate copy, stray
  words, pipe separators, or garbled glyphs are a FAIL.
- For English marketing creatives, floating screenshot boxes, pasted-looking
  device rectangles, dead split columns, fake repeated-card grids, dashboard or
  moodboard layouts, and purposeless empty regions are a FAIL unless explicitly
  requested.
- A legal/RUO footer closer than 5 percent of canvas height to the bottom edge
  is a FAIL. A model-native surgical edit is the preferred repair; do not hide
  the failure with an external assembled overlay.
- If `qr_zone=reserve`, the render must contain a clean, intentional square safe
  panel at least 18 percent of the shorter dimension, clear of copy and at least
  5 percent from every edge. QR-like noise drawn by the model is a FAIL.
- A final deliverable containing a QR must have a deterministic receipt from
  `.archon/scripts/image-qr.py` and machine-decode to the exact approved HTTPS URL.
  A QR that merely looks correct, decodes to another URL, or was invented by the
  image model is a FAIL.
- Any exact-text, brand or logo, likeness, or public-figure risk requires manual
  review even if the dry-run passes.
- When `$intake.output.subject_mode` is `placeholder`: the literal token
  `[SUBJECT SUPPLIED AT RENDER TIME]` in every prompt's `Subject:` field is
  REQUIRED, not a defect. Flag as an issue only its ABSENCE, or any invented
  physical subject traits alongside it. (The deterministic validate-pack node
  has already hard-failed structural violations; this pass is semantic.)

## QA Report

The markdown report must include:
- verdict
- render_status and render_mode
- artifacts checked
- issues
- manual review notes
- next local test command

## QA JSON Shape

```json
{
  "pass": "true",
  "render_status": "prompt_pack_only",
  "render_mode": "overlay",
  "manual_review_required": "false",
  "issue_count": 0,
  "qa_report_path": "qa-report.md"
}
```

## Final Requirement

Write the QA report first. Then output only valid JSON matching the QA shape. No
markdown, no commentary.
