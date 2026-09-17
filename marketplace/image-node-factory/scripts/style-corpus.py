#!/usr/bin/env python3
"""Deterministic retrieval over pinned image-prompt sources with distinct licenses.

Ported skill: `gpt-image-2-style-library` (upstream: awesome-gpt-image-2).

The installed skill ships an INDEX: taxonomy, template names, and bare case ids.
The template bodies and the worked cases live upstream. A workflow node running
with `webSearchMode: disabled` cannot follow those URLs, so a citation of
`example_case_ids` resolves to nothing unless the corpus is provisioned first.

The port contract (docs/manual/features/skill-to-workflow-port.md):

    prime    ONLINE. The only network step. Never runs inside a DAG.
    ground   PURE and OFFLINE. Resolves a selection into real cases, or
             reports grounded=false. Never touches the network.

A citation is stamped if and only if it resolves. Zero matches is an honest
`grounded: false` (exit 0). A cold or corrupt cache is a provisioning failure
(exit 1), not a data answer.

No upstream text is embedded in this file. It is fetched, verified, and cached
outside the repository tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style_sources as sources

SKILL_NAME = "gpt-image-2-style-library"
_LOCK = sources.manifest()["primary"]
UPSTREAM_REPO = _LOCK["repo"]
UPSTREAM_PIN = _LOCK["active_pin"]
UPSTREAM_LICENSE = _LOCK["license"]
UPSTREAM_HOME = f"https://github.com/{UPSTREAM_REPO}"
_RAW = "https://raw.githubusercontent.com/{repo}/{pin}/{path}"
PINNED_FILES = {
    pin: {name: (entry["path"], entry["sha256"]) for name, entry in data["files"].items()}
    for pin, data in _LOCK["pins"].items()
}
CORPUS_FILES = PINNED_FILES[UPSTREAM_PIN]


def _files_for(pin):
    if pin not in PINNED_FILES:
        raise CorpusMissing(f"unregistered corpus pin: {pin}; add reviewed hashes first")
    return PINNED_FILES[pin]


CACHE_ENV = "ARCHON_PORT_CACHE_DIR"

_DEFAULT_K = 5
_EXEMPLAR_CHAR_CAP = 32000
_EXEMPLAR_TOTAL_BUDGET = 32000
_HTTP_TIMEOUT_S = 60

_W_CATEGORY = 3
_W_STYLE = 2
_W_SCENE = 1
_W_EXAMPLE_CASE = 4

# CJK ideographs plus CJK/fullwidth punctuation. Escaped rather than literal so this
# file stays pure ASCII: it is read and piped by toolchains that default to cp1252.
# Used only to offer an English-exemplar filter; the corpus is bilingual by design.
_CJK = re.compile("[\u3000-\u9fff\uff00-\uffef]")


class CorpusMissing(RuntimeError):
    """Cache absent, incomplete, or byte-for-byte wrong. Exit 1: provisioning bug."""


class UsageError(RuntimeError):
    """Bad arguments. Exit 1."""


@dataclass(frozen=True)
class Case:
    id: int
    title: str
    prompt: str
    category: str
    styles: tuple[str, ...]
    scenes: tuple[str, ...]
    featured: bool
    source_url: str
    ref: str = ""
    source: str = "freestylefly"
    author: str = ""


@dataclass(frozen=True)
class Template:
    id: str
    category: str
    anchor: str
    styles: tuple[str, ...]
    scenes: tuple[str, ...]
    example_cases: tuple[int, ...]


@dataclass(frozen=True)
class Corpus:
    root: Path
    pin: str
    cases: dict[int, Case]
    templates: dict[str, Template]
    supplemental: dict[str, Case] = field(default_factory=dict)
    source_info: dict = field(default_factory=dict)

    @property
    def template_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.templates))


@dataclass(frozen=True)
class Exemplar:
    id: int
    title: str
    prompt: str
    category: str
    styles: tuple[str, ...]
    scenes: tuple[str, ...]
    source_url: str
    truncated: bool
    ref: str = ""
    author: str = ""


@dataclass(frozen=True)
class Grounding:
    grounded: bool
    matched: int
    resolved_case_ids: tuple[int, ...]
    unresolved_case_ids: tuple[int, ...]
    exemplars: tuple[Exemplar, ...] = ()
    provenance: dict = field(default_factory=dict)
    excluded: tuple[dict, ...] = ()

    def summary(self) -> dict:
        """Small payload for stdout, so `$node.output.grounded` stays cheap."""
        out = {
            "grounded": self.grounded,
            "matched": self.matched,
            "resolved_case_ids": list(self.resolved_case_ids),
            "unresolved_case_ids": list(self.unresolved_case_ids),
        }
        out.update(self.provenance)
        return out

    def full(self) -> dict:
        payload = self.summary()
        payload["excluded_examples"] = list(self.excluded)
        payload["exemplars"] = [
            {
                "id": e.id,
                "ref": e.ref or f"freestylefly:{e.id}",
                "author": e.author,
                "title": e.title,
                "prompt": e.prompt,
                "category": e.category,
                "styles": list(e.styles),
                "scenes": list(e.scenes),
                "source_url": e.source_url,
                "truncated": e.truncated,
            }
            for e in self.exemplars
        ]
        return payload


def _http_get(url: str) -> bytes:
    """Network seam. Kept a module-level name so tests can monkeypatch it (Rule 3)."""
    req = urllib.request.Request(url, headers={"User-Agent": "archon-skill-port"})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:  # noqa: S310
        return resp.read()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cache_root(explicit: "str | Path | None" = None) -> Path:
    """Repo-independent by construction: a global workflow must find the same cache
    no matter which repository it was launched from."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get(CACHE_ENV)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".archon" / "cache" / "skill-ports"


def corpus_dir(*, pin: "str | None" = None, cache_dir=None) -> Path:
    return cache_root(cache_dir) / SKILL_NAME / (pin or UPSTREAM_PIN)


def prime(*, pin=None, cache_dir=None, force=None) -> Path:
    """ONLINE. Fetch, verify, and atomically install the corpus. Never called in a DAG."""
    resolved_pin = pin or UPSTREAM_PIN
    files = _files_for(resolved_pin)
    force = bool(force)
    target = corpus_dir(pin=resolved_pin, cache_dir=cache_dir)

    if target.is_dir() and not force:
        try:
            require_corpus(pin=resolved_pin, cache_dir=cache_dir)
            return target
        except CorpusMissing:
            pass  # present but wrong: fall through and refetch

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{resolved_pin[:8]}.tmp.", dir=target.parent))
    try:
        for name, (path, expected) in files.items():
            raw = _http_get(_RAW.format(repo=UPSTREAM_REPO, pin=resolved_pin, path=path))
            actual = _sha256(raw)
            if actual != expected:
                raise CorpusMissing(
                    f"{path}: sha256 mismatch at pin {resolved_pin[:8]}\n"
                    f"  expected {expected}\n  actual   {actual}\n"
                    "Refusing to write an unverified corpus."
                )
            (staging / name).write_bytes(raw)

        if target.is_dir():
            shutil.rmtree(target)
        os.replace(staging, target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def require_corpus(*, pin=None, cache_dir=None) -> Corpus:
    """Rule 2: decide validity by re-hashing the actual bytes on every call."""
    resolved_pin = pin or UPSTREAM_PIN
    root = corpus_dir(pin=resolved_pin, cache_dir=cache_dir)
    hint = (
        f"corpus not provisioned at {root}\n"
        f"  run: uv run .archon/scripts/style-corpus.py prime"
    )
    if not root.is_dir():
        raise CorpusMissing(hint)

    for name, (_path, expected) in _files_for(resolved_pin).items():
        f = root / name
        if not f.is_file():
            raise CorpusMissing(f"{hint}\n  missing file: {name}")
        actual = _sha256(f.read_bytes())
        if actual != expected:
            raise CorpusMissing(
                f"{hint}\n  corrupt file: {name}\n"
                f"  expected {expected}\n  actual   {actual}"
            )

    return _load(root, resolved_pin)


def _load(root: Path, pin: str) -> Corpus:
    raw_cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
    cases: dict[int, Case] = {}
    for c in raw_cases["cases"]:
        prompt = str(c.get("prompt") or "")
        if not prompt.strip():
            continue  # a case with no prompt cannot ground a citation
        cases[int(c["id"])] = Case(
            id=int(c["id"]),
            title=str(c.get("title") or ""),
            prompt=prompt,
            category=str(c.get("category") or ""),
            styles=tuple(c.get("styles") or ()),
            scenes=tuple(c.get("scenes") or ()),
            featured=bool(c.get("featured")),
            source_url=str(c.get("sourceUrl") or ""),
            author=str(c.get("sourceLabel") or ""),
        )

    raw_lib = json.loads((root / "style-library.json").read_text(encoding="utf-8"))
    templates: dict[str, Template] = {}
    for t in raw_lib.get("templates", ()):
        templates[str(t["id"])] = Template(
            id=str(t["id"]),
            category=str(t.get("category") or ""),
            anchor=str(t.get("templateAnchor") or ""),
            styles=tuple(t.get("styles") or ()),
            scenes=tuple(t.get("scenes") or ()),
            example_cases=tuple(int(x) for x in (t.get("exampleCases") or ())),
        )
    extra, info = {}, {}
    if pin == UPSTREAM_PIN:
        try:
            included, _catalog, info = sources.load(root.parent.parent)
        except sources.SourceError as exc:
            raise CorpusMissing(str(exc)) from exc
        for row in included:
            extra[row["ref"]] = Case(
                id=0, title=row["title"], prompt=row["prompt"], category=row["category"],
                styles=tuple(row.get("styles", [])), scenes=tuple(row.get("scenes", [])),
                featured=False, source_url=row["source_url"], ref=row["ref"],
                source=row["source"], author=row["author"],
            )
    return Corpus(root=root, pin=pin, cases=cases, templates=templates,
                  supplemental=extra, source_info=info)


def _truncate(prompt: str, cap: int) -> tuple[str, bool]:
    if len(prompt) <= cap:
        return prompt, False
    cut = prompt[:cap]
    nl = cut.rfind("\n")
    if nl > cap // 2:
        cut = cut[:nl]
    return cut.rstrip(), True


def _provenance(corpus: Corpus) -> dict:
    return {
        "prompt_engine": SKILL_NAME,
        "corpus_pin": corpus.pin,
        "corpus_source": UPSTREAM_HOME,
        "corpus_sha256": _files_for(corpus.pin)["cases.json"][1],
        "license": UPSTREAM_LICENSE,
    }


def _ref(case):
    return case.ref or f"freestylefly:{case.id}"


def _record(case):
    return {"ref": _ref(case), "title": case.title, "prompt": case.prompt,
            "category": case.category, "styles": list(case.styles), "scenes": list(case.scenes)}


def select(corpus: Corpus, *, template_id=None, category=None, styles=None,
           scenes=None, case_ids=None, case_refs=None, lang=None, k=None, query=None) -> Grounding:
    """Offline lexical + taxonomy retrieval with legacy integer anchors.

    Complete examples only; reference data cannot alter workflow instructions.
    Exact text duplicates share aliases. A shared article URL alone is NOT a
    duplicate: a single article can contain several different useful prompts.
    """
    k = min(5, max(1, _DEFAULT_K if k is None else int(k)))
    lang = (lang or "").lower() or None
    tpl = corpus.templates.get(template_id) if template_id else None
    if template_id and tpl is None:
        raise UsageError(f"unknown template_id: {template_id}")
    want_styles, want_scenes = set(styles or ()), set(scenes or ())
    example_ids = set(tpl.example_cases) if tpl else set()
    pool = list(corpus.cases.values()) + list(corpus.supplemental.values())
    if lang == "en":
        pool = [c for c in pool if not _CJK.search(c.prompt)]
    if query and category and any(c.category == category for c in pool):
        explicit = set(case_refs or ()) | {f"freestylefly:{int(i)}" for i in (case_ids or ())}
        pool = [c for c in pool if c.category == category or _ref(c) in explicit]
    available = {_ref(c): c for c in pool}
    lexical = sources.lexical_scores(query or "", [_record(c) for c in pool])
    requested = [f"freestylefly:{int(i)}" for i in (case_ids or ())] + list(case_refs or ())
    anchors, unresolved, seen = [], [], set()
    for ref in requested:
        if ref not in available:
            unresolved.append(ref)
        elif ref not in seen:
            anchors.append(available[ref]); seen.add(ref)
    scored = []
    for c in pool:
        if _ref(c) in seen:
            continue
        score = lexical[_ref(c)] * 3
        score += _W_CATEGORY if category and c.category == category else 0
        score += _W_STYLE * len(want_styles.intersection(c.styles))
        score += _W_SCENE * len(want_scenes.intersection(c.scenes))
        if c.source == "freestylefly" and c.id in example_ids:
            score += _W_EXAMPLE_CASE
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda sc: (-sc[0], not sc[1].featured, _ref(sc[1])))
    ranked = anchors + [c for _score, c in scored]
    byhash = {}
    for c in pool:
        byhash.setdefault(sources.sha(sources.normal(c.prompt).encode()), []).append(c)
    chosen, excluded, fingerprints = [], [], set()
    budget = _EXEMPLAR_TOTAL_BUDGET
    for c in ranked:
        fingerprint = sources.sha(sources.normal(c.prompt).encode())
        if fingerprint in fingerprints:
            excluded.append({"ref":_ref(c), "reason":"duplicate_prompt"})
            continue
        if len(c.prompt) > budget:
            excluded.append({"ref":_ref(c), "reason":"complete_prompt_exceeds_remaining_budget", "characters":len(c.prompt)})
            continue
        chosen.append(c); fingerprints.add(fingerprint); budget -= len(c.prompt)
        if len(chosen) == k:
            break
    exemplars = tuple(Exemplar(c.id, c.title, c.prompt, c.category, c.styles, c.scenes,
                              c.source_url, False, _ref(c), c.author) for c in chosen)
    provenance = _provenance(corpus) if chosen else {}
    if chosen:
        aliases, citations, source_ids = {}, [], set()
        for c in chosen:
            group = byhash[sources.sha(sources.normal(c.prompt).encode())]
            aliases[_ref(c)] = sorted(_ref(a) for a in group if _ref(a) != _ref(c))
            for alias in group:
                source_ids.add(alias.source)
                citations.append({"ref":_ref(alias),"author":alias.author,"source_url":alias.source_url,
                                  "changes":"Used as a structural reference; generated wording is new."})
        primary = {"id":"freestylefly", "repo":UPSTREAM_REPO, "pin":corpus.pin,
                   "sha256":_files_for(corpus.pin)["cases.json"][1], "license":"MIT",
                   "license_url":_LOCK["license_url"]}
        source_list = [primary if sid == "freestylefly" else corpus.source_info[sid] for sid in sorted(source_ids)]
        licenses = sorted({s["license"] for s in source_list})
        provenance.update(schema_version=2, resolved_case_refs=[_ref(c) for c in chosen],
                          unresolved_case_refs=unresolved, sources=source_list, citations=citations,
                          aliases=aliases, license=licenses[0] if len(licenses)==1 else "MIXED")
    return Grounding(bool(chosen), len(ranked),
                     tuple(c.id for c in chosen if c.source=="freestylefly"),
                     tuple(int(r.split(":",1)[1]) for r in unresolved if r.startswith("freestylefly:") and r.split(":",1)[1].isdigit()),
                     exemplars, provenance, tuple(excluded))


def candidate_catalog(corpus, query, category=None, limit=24):
    cases = list(corpus.cases.values()) + list(corpus.supplemental.values())
    if category and any(c.category == category for c in cases):
        cases = [c for c in cases if c.category == category]
    scores = sources.lexical_scores(query, [_record(c) for c in cases])
    ordered = sorted(cases, key=lambda c: (-(scores[_ref(c)] * 3 + (3 if c.category==category else 0)), _ref(c)))
    result, seen = [], set()
    for c in ordered:
        fingerprint = sources.sha(sources.normal(c.prompt).encode())
        score = scores[_ref(c)] * 3 + (3 if c.category==category else 0)
        if score <= 0 or fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append({"ref":_ref(c),"title":c.title,"category":c.category,"styles":list(c.styles),
                       "scenes":list(c.scenes),"characters":len(c.prompt),"score":round(score,4),"source_url":c.source_url})
        if len(result) >= limit:
            break
    return result


def active_index(corpus):
    cases = list(corpus.cases.values()) + list(corpus.supplemental.values())
    groups, links = {}, {}
    for case in cases:
        groups.setdefault(sources.sha(sources.normal(case.prompt).encode()), []).append(case)
        if case.source_url:
            links.setdefault(sources.source_identity(case.source_url), []).append(_ref(case))
    rows = []
    for digest, group in sorted(groups.items(), key=lambda pair: min(_ref(c) for c in pair[1])):
        ordered = sorted(group, key=_ref)
        first = ordered[0]
        rows.append({"ref":_ref(first), "aliases":[_ref(c) for c in ordered[1:]],
                     "title":first.title, "category":first.category,
                     "styles":list(first.styles), "scenes":list(first.scenes),
                     "prompt_sha256":digest, "characters":len(first.prompt),
                     "citations":[{"ref":_ref(c),"author":c.author,"source_url":c.source_url} for c in ordered]})
    return {"schema_version":2, "primary_pin":corpus.pin, "record_count":len(cases),
            "unique_prompt_count":len(rows), "template_ids":list(corpus.template_ids),
            "cases":rows, "shared_source_links":{url:sorted(refs) for url,refs in sorted(links.items()) if len(refs)>1}}


def _cmd_index(args):
    print(json.dumps(active_index(require_corpus(pin=args.pin, cache_dir=args.cache_dir)), ensure_ascii=False, indent=2))
    return 0


def _cmd_candidates(args):
    artifacts = Path(os.environ["ARTIFACTS_DIR"])
    brief = json.loads((artifacts / "image-node-brief.json").read_text(encoding="utf-8"))
    corpus = require_corpus(cache_dir=args.cache_dir)
    query = str(brief.get("brief") or brief.get("request") or brief.get("primary_request") or json.dumps(brief))
    candidates = candidate_catalog(corpus, query, brief.get("category_hint"))
    payload = {"schema_version":2,"candidates":candidates,"template_ids":list(corpus.template_ids)}
    (artifacts / "image-node-candidates.local.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"candidate_count":len(candidates),"catalog":"image-node-candidates.local.json"}))
    return 0


def template_body(corpus: Corpus, template_id: str) -> str:
    tpl = corpus.templates.get(template_id)
    if tpl is None:
        raise UsageError(f"unknown template_id: {template_id}")
    doc = (corpus.root / "templates.md").read_text(encoding="utf-8")
    anchor = tpl.anchor or ""
    start = doc.find(f'<a name="{anchor}"></a>')
    if start < 0:
        raise UsageError(f"template anchor not found in templates.md: {anchor!r}")
    nxt = doc.find('<a name="tpl-', start + 1)
    return doc[start : nxt if nxt > 0 else len(doc)].strip()


def _csv(value: "str | None") -> "list[str] | None":
    if not value:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def _selection_from_artifacts(artifacts: Path) -> dict:
    sel = artifacts / "image-node-selection.json"
    if not sel.is_file():
        raise UsageError(f"missing upstream artifact: {sel}")
    return json.loads(sel.read_text(encoding="utf-8"))


def _cmd_ground(args) -> int:
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        raise UsageError("ARTIFACTS_DIR is not set; `ground` runs inside an Archon node")
    artifacts_dir = Path(artifacts)

    corpus = require_corpus(cache_dir=args.cache_dir)
    sel = _selection_from_artifacts(artifacts_dir)

    ids = sel.get("example_case_ids") or sel.get("case_ids") or None
    if ids:
        ids = [int(re.sub(r"[^0-9]", "", str(i)) or -1) for i in ids]

    grounding = select(
        corpus,
        template_id=sel.get("template_id") or None,
        category=sel.get("category") or None,
        styles=sel.get("style_tags") or None,
        scenes=sel.get("scene_tags") or None,
        case_ids=ids,
        case_refs=sel.get("example_case_refs"),
        query=sel.get("retrieval_query"),
        lang=args.lang,
        k=args.k,
    )

    # Full exemplar bodies stay in a *.local.json: excluded from the publishable
    # pack, and $ARTIFACTS_DIR already lives outside the repository tree.
    out = artifacts_dir / "image-node-grounding.local.json"
    out.write_text(json.dumps(grounding.full(), ensure_ascii=False, indent=2), encoding="utf-8")

    summary = grounding.summary()
    summary["grounding_path"] = str(out)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def _cmd_prime(args) -> int:
    if not args.pin or args.pin == UPSTREAM_PIN:
        sources.prime(args.cache_dir)
    root = prime(pin=args.pin, cache_dir=args.cache_dir, force=args.force)
    corpus = require_corpus(pin=args.pin, cache_dir=args.cache_dir)
    print(
        json.dumps(
            {
                "primed": str(root),
                "pin": corpus.pin,
                "cases": len(corpus.cases),
                "templates": len(corpus.templates),
                "template_ids": list(corpus.template_ids),
                "license": UPSTREAM_LICENSE,
            },
            indent=2,
        )
    )
    return 0


def _cmd_verify(args) -> int:
    corpus = require_corpus(pin=args.pin, cache_dir=args.cache_dir)
    print(json.dumps({"ok": True, "pin": corpus.pin, "cases": len(corpus.cases)}))
    return 0


def _cmd_stats(args) -> int:
    corpus = require_corpus(pin=args.pin, cache_dir=args.cache_dir)
    by_cat: dict[str, int] = {}
    english = 0
    for c in corpus.cases.values():
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
        if not _CJK.search(c.prompt):
            english += 1
    print(
        json.dumps(
            {
                "pin": corpus.pin,
                "cases": len(corpus.cases),
                "english_prompts": english,
                "templates": len(corpus.templates),
                "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _cmd_select(args) -> int:
    corpus = require_corpus(pin=args.pin, cache_dir=args.cache_dir)
    ids = [int(x) for x in (_csv(args.cases) or ())] or None
    grounding = select(
        corpus,
        template_id=args.template_id,
        category=args.category,
        styles=_csv(args.styles),
        scenes=_csv(args.scenes),
        case_ids=ids,
        case_refs=_csv(args.refs),
        query=args.query,
        lang=args.lang,
        k=args.k,
    )
    payload = grounding.full() if args.full else grounding.summary()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _cmd_template(args) -> int:
    corpus = require_corpus(pin=args.pin, cache_dir=args.cache_dir)
    print(template_body(corpus, args.template_id))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="style-corpus", description=__doc__.splitlines()[0])
    p.add_argument("--pin", default=None)
    p.add_argument("--cache-dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("prime", help="ONLINE: fetch + verify + install the corpus")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=_cmd_prime)

    sv = sub.add_parser("verify", help="re-hash the cached bytes")
    sv.set_defaults(func=_cmd_verify)

    ss = sub.add_parser("stats", help="corpus counts")
    ss.set_defaults(func=_cmd_stats)

    sl = sub.add_parser("select", help="deterministic retrieval")
    sl.add_argument("--template-id", default=None)
    sl.add_argument("--category", default=None)
    sl.add_argument("--styles", default=None, help="comma separated")
    sl.add_argument("--scenes", default=None, help="comma separated")
    sl.add_argument("--cases", default=None, help="comma separated ids")
    sl.add_argument("--refs", default=None, help="comma separated source-qualified references")
    sl.add_argument("--query", default=None)
    sl.add_argument("--lang", default=None, choices=["en"])
    sl.add_argument("--k", type=int, default=None)
    sl.add_argument("--full", action="store_true", help="include exemplar bodies")
    sl.set_defaults(func=_cmd_select)

    st = sub.add_parser("template", help="print a template body")
    st.add_argument("template_id")
    st.set_defaults(func=_cmd_template)

    sg = sub.add_parser("ground", help="OFFLINE: Archon node entrypoint")
    sg.add_argument("--lang", default=None, choices=["en"])
    sg.add_argument("--k", type=int, default=None)
    sg.set_defaults(func=_cmd_ground)
    sub.add_parser("index", help="OFFLINE: complete active case index with provenance aliases").set_defaults(func=_cmd_index)
    sub.add_parser("candidates", help="OFFLINE: generate brief-specific candidate index").set_defaults(func=_cmd_candidates)
    sub.add_parser("update-report", help="ONLINE: compare upstream, never activate").set_defaults(
        func=lambda args: print(json.dumps(sources.update_report(args.cache_dir),indent=2)) or 0)
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        # Archon's named-script dispatch runs `uv run <path>` with no arguments,
        # and `ground` is the only thing a node ever needs.
        argv = ["ground"]
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CorpusMissing, UsageError, sources.SourceError, OSError, ValueError) as exc:
        print(f"style-corpus: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
