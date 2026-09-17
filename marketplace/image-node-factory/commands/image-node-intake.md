---
description: Parse a visual brief into the Image Node Factory intake JSON.
argument-hint: "<visual brief with optional category/render_mode/aspect/count/parallelism/render/design_file/persona_pack/exact_text/qr_zone controls>"
---

# Image Node Intake

**Workflow ID**: $WORKFLOW_ID

## Contract

You are the intake node for a marketplace-public Archon workflow. Parse the
operator's visual brief into a compact, deterministic brief JSON. Do not choose a
template here. Do not render images. Do not call OpenAI APIs. Do not embed
absolute local run paths or private system names in the output.

Read:
- Original request: `$ARGUMENTS`
- Preflight artifact: `$ARTIFACTS_DIR/image-node-preflight.json`

Write:
- `$ARTIFACTS_DIR/image-node-brief.json`

Then output ONLY the same JSON object.

## Inline Controls

Respect explicit inline controls when present in the brief:
- `category=` a library category name or the word `auto` (default `auto`)
- `render_mode=` `baked` or `overlay` (default `baked` for visible English
  marketing copy; `overlay` is an explicit precision fallback)
- `aspect=` a ratio or size
- `count=` a number, never above 10
- `parallelism=` a number from 1 to 3 (default `3` when `count` is greater
  than 1; otherwise `1`). This controls the single global render coordinator,
  never independent workflow fan-out.
- `render=` `true` or `false`
- `design_file=` an optional relative brand design reference, or `none`
- `persona_pack=` an optional relative subject reference, or `none`
- `subject_mode=` `generic` or `placeholder` (default `generic`). In
  `placeholder` mode the prompt pack must NOT invent a subject: every prompt
  carries a literal `[SUBJECT SUPPLIED AT RENDER TIME]` slot for a downstream
  renderer to fill with its own reference-locked subject.
- `exact_text="..."` verbatim copy for the baked variant
- `qr_zone=` `none` or `reserve` (default `none`). `reserve` asks the image
  model for an intentional square safe zone only. A real QR is generated and
  decode-verified after rendering from a separately approved URL.

## Render Mode

- `render_mode` selects which variant the render node will generate later. It
  does NOT restrict the prompt pack. The prompt pack always emits both a baked
  variant and an overlay variant so the two can be compared.
- Respect an explicit `render_mode` exactly.
- When the brief requests an English ad, social creative, poster, infographic,
  packaging concept, or other marketing image with visible copy, default to
  `baked`. The model should design typography and imagery as one integrated
  composition.
- Use `overlay` only when the operator explicitly requests it, or when the brief
  requires deterministic localization, non-Latin text, legal copy that cannot
  tolerate model variation, or an external brand-font renderer.
- If `exact_text` is non-empty and no explicit mode is supplied, choose `baked`.
- `render_requested` comes from the preflight JSON unless the brief clearly sets
  `render=`.

## Category Hint

Do not lock a template. Emit `category_hint` as one of the library categories
below, or `auto` when the brief does not clearly imply one. The select node does
the authoritative, skill-backed template choice.

Library categories:
- `UI & Interfaces`
- `Charts & Infographics`
- `Posters & Typography`
- `Products & E-commerce`
- `Brand & Logos`
- `Architecture & Spaces`
- `Photography & Realism`
- `Illustration & Art`
- `Characters & People`
- `Scenes & Storytelling`
- `History & Classical Themes`
- `Documents & Publishing`
- `Other Use Cases`

## Parsing Rules

- If `exact_text` is present, copy the quoted value exactly. If the request asks
  for visible text but does not quote it, put the best literal phrase in
  `exact_text` and add `text-not-verbatim-confirmed` to `risk_flags`.
- Default `aspect` by category hint when the brief gives none:
  - `Products & E-commerce`: `1:1`
  - `Posters & Typography`: `2:3`
  - `Charts & Infographics`: `16:9`
  - `UI & Interfaces`: `16:9`
  - `Brand & Logos`: `1:1`
  - `Architecture & Spaces`: `16:9`
  - `Characters & People`: `4:5`
  - `Scenes & Storytelling`: `16:9`
  - anything else: `1:1`
- Keep `count` from the preflight JSON unless the brief clearly requests fewer
  assets. Never exceed 10.
- Clamp `parallelism` to 1 through 3 and never above `count`. Ten requested
  assets means ten total jobs through at most three global render slots, not ten
  simultaneous Codex or Archon processes.
- `design_file` and `persona_pack` are optional runtime references only. If the
  brief supplies neither, set both to `none`. Never invent a value, and never
  substitute a brand name, a persona name, or an absolute local path.
- `subject_mode` defaults to `generic`. Set `placeholder` only when the brief
  says so explicitly. A `placeholder` brief that also sets `render=true` with
  `persona_pack=none` should carry the `reference-image-needed` risk flag: the
  pack expects a render-time subject that this run cannot supply.
- `qr_zone` defaults to `none`. Set `reserve` only when the brief asks for a QR,
  scannable code, or deliberate QR placement. Never place a destination URL in
  this marketplace-public brief artifact and never ask the image model to draw
  the QR itself.
- Risk flags should include only applicable values, such as: `exact-text-risk`,
  `likeness-risk`, `brand-logo-risk`, `public-figure-risk`,
  `reference-image-needed`, `manual-review-needed`.
- Constraints must use public-generic wording. Use the phrase
  `no private workflow, local-system, or persona-reference details` when a
  constraint needs to cover private or internal context.

## Required JSON Shape

```json
{
  "brief": "",
  "render_requested": "false",
  "render_mode": "baked",
  "count": 1,
  "parallelism": 1,
  "subject_mode": "generic",
  "qr_zone": "none",
  "category_hint": "auto",
  "aspect": "1:1",
  "exact_text": "",
  "style_tags": [],
  "subject_tags": [],
  "design_file": "none",
  "persona_pack": "none",
  "brand_context": "",
  "constraints": ["no private workflow, local-system, or persona-reference details"],
  "risk_flags": []
}
```

## Final Requirement

Write the artifact first. Then output only valid JSON matching the required
shape. No markdown, no commentary.
