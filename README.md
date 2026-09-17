# Image Node Factory

A portable Archon workflow: brief -> offline candidates -> AI selection -> verified grounding -> fresh prompt pack -> validation -> optional Codex built-in images.

## September 2026 corpus

- 541 primary examples and 22 templates from freestylefly (MIT).
- 13 curated supplemental examples from ZeroLu (MIT) and YouMind (CC BY 4.0).
- 198 supplementary entries reviewed; inclusion/exclusion decisions are shipped as metadata.
- Full source prompts are downloaded into the user cache, never vendored here.
- Source pins, SHA-256 hashes, author links, licenses and adaptation notices are retained.

The September refresh is a review candidate. Live comparison images were blocked by the configured image endpoint; no visual quality improvement or completed live render run is claimed.

Install with `archon workflow install image-node-factory`, then run `uv run .archon/scripts/style-corpus.py prime` once. Generation stays offline with respect to corpus retrieval.

Use `render=false` for prompt packs, or `render=true` for Codex built-in images. The render approval stages remain in the workflow. Both baked and text-free overlay variants are produced. English marketing copy defaults to baked; overlay is an explicit precision fallback.

Controls: `count=1..10`, `aspect=4:5`, `render_mode=baked|overlay`, `subject_mode=generic|placeholder`, `exact_text="..."`, `qr_zone=none|reserve`. Placeholder subjects block rendering until a suitable reference is supplied.

## Source tools

- `style-corpus.py index` builds the full active case index offline.
- `style-corpus.py verify` checks physical cache bytes.
- `style-corpus.py select --query "lemon beverage campaign" --full` retrieves complete examples.
- `style-corpus.py select --cases 532` retains legacy integer IDs.
- `style-corpus.py select --refs youmind:34675 --full` uses source-qualified IDs.
- `style-corpus.py update-report` compares upstream without changing the installation.
- Global options `--pin` and `--cache-dir` go before the command. Only registered, hash-locked primary pins are accepted, including the July rollback pin.

Schema 2 adds example_case_refs, sources, citations and aliases. Legacy single-source packs remain supported. Mixed-source attribution is validated against the source lock and physical grounding. Complete exemplars are limited to five and 32,000 characters in total; oversized examples are reported rather than silently truncated.

## Portable and private behavior

This package renders sequentially through the Codex built-in tool and validates files and geometry. It has no dependency on a private Homie checkout. Homie's three-slot coordinator, private brand configuration and identity assets are intentionally absent. No API-key renderer fallback is used.

QR composition is optional and deterministic: `uv run --with 'qrcode[pil]' --with zxing-cpp .archon/scripts/image-qr.py --help`. Generated images do not draw QR modules themselves.

## Verification

`uv run --with pytest --with pyyaml --with pillow --with 'qrcode[pil]' --with zxing-cpp pytest tests -q`

Tests use synthetic fixtures. The optional active-cache test skips when the corpus has not been provisioned.

## Attribution

Source repositories and license notices are recorded in `marketplace/image-node-factory/scripts/style-sources.json`. The workflow code is MIT licensed; third-party source licenses remain distinct. Prompt adaptations retain source attribution and do not imply endorsement.
