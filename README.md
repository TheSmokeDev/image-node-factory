# Image Node Factory

An [Archon](https://archon.diy) workflow that turns one natural-language visual
brief into a production-ready image **prompt pack** -- and, optionally, rendered
bitmaps via Codex built-in image generation. Built for marketing assets: posters,
product shots, spokesperson heroes, brand boards, infographics.

```bash
archon workflow install image-node-factory

# one-time, per machine: provision the pinned style corpus (the only network step)
uv run .archon/scripts/style-corpus.py prime

# then: one sentence in, a validated prompt pack out
archon workflow run image-node-factory \
  "confident spokesperson hero for a modern service brand, count=4 aspect=4:5 render_mode=baked"
```

## What makes it different

**AI decides, script resolves, AI consumes.** The style intelligence comes from
the MIT-licensed `awesome-gpt-image-2` corpus -- 511 worked cases and 22
structured templates -- pinned to a commit and checksum-verified on every read.
An AI node picks the template and cites case ids; a deterministic script resolves
those ids offline against the pinned corpus. **A citation either resolves or is
never stamped.** When nothing matches, the pack honestly declares
`self_authored: true` instead of name-dropping a library it never read.

A second deterministic node, `validate-pack`, re-checks the finished pack against
the physical grounding artifact and fails the run on any violation: a hollow
citation, a cited case the corpus never resolved, mismatched provenance, more
than 8 concepts, an empty prompt variant, or an absolute local path in pack text.

## The DAG

```
preflight -> intake -> select -> ground -> prompt-pack -> validate-pack -> render -> qa -> report
             (AI)     (AI)     (script)      (AI)          (script)      (AI, opt)
```

Every concept ships BOTH variants, so you choose per post with no re-run:

| Discipline | Meaning |
|---|---|
| `baked`   | Copy rendered inside the image |
| `overlay` | Text-free scene + a separate copy JSON for crisp HTML overlay |

## Inline controls

All parsed from the one brief string -- no YAML editing per run:

```
category=<corpus category|auto>   render_mode=baked|overlay   aspect=<ratio>
count=<1..8>                      render=true|false           exact_text="..."
design_file=<path|none>           persona_pack=<path|none>
subject_mode=generic|placeholder
```

`subject_mode=placeholder` is the brand-agnostic subject slot: the pack never
invents a person or mascot -- every prompt carries a literal
`[SUBJECT SUPPLIED AT RENDER TIME]` token your own renderer fills with its
reference-locked subject. `validate-pack` enforces the token's presence; `render`
blocks rather than drawing it literally.

## Safety

- Default is `render=false`: prompt pack only, no image generation.
- No API keys, no external services -- rendering uses Codex built-in image
  generation only, and blocks cleanly when unavailable.
- No node fetches the network. The corpus is provisioned once, out of band, by
  `prime`, and lives at `~/.archon/cache/` -- it never enters your repo.
- Packs are publish-safe by construction: no absolute paths, no invented brands,
  people, or claims.

## Layout

```
marketplace/image-node-factory/
├── image-node-factory.yaml   # the workflow DAG
├── commands/                 # 6 node prompts        -> .archon/commands/
├── scripts/                  # style-corpus.py,
│                             # pack-validate.py      -> .archon/scripts/
└── image-nodes/              # 7 discipline cards    -> .archon/image-nodes/
```

## Attribution

Style corpus: [`freestylefly/awesome-gpt-image-2`](https://github.com/freestylefly/awesome-gpt-image-2)
(MIT). The corpus is retrieved at provision time and attributed on every grounded
artifact; it is never vendored into this repository.

-- SmokeDev
