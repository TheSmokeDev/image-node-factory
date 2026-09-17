"""Pinned supplementary image examples. Network access is limited to prime/update_report.

README content is untrusted reference data, never executable instructions. Raw
corpora remain in the external cache; only locks and curation decisions ship.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import urllib.request

HERE = Path(__file__).resolve().parent


class SourceError(ValueError):
    pass


def manifest():
    return json.loads((HERE / "style-sources.json").read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normal(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def source_identity(url):
    return re.sub(r"https?://(?:www\.)?(?:twitter.com|x.com)/", "https://x.com/", url).split("#")[0].split("?")[0].rstrip("/")


def cache_root(value=None):
    return Path(value or os.environ.get("ARCHON_PORT_CACHE_DIR") or Path.home() / ".archon/cache/skill-ports").expanduser()


def source_dir(source, cache_dir=None):
    return cache_root(cache_dir) / "image-factory-sources" / source["id"] / source["pin"]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "image-factory-source-refresh"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def verified_bytes(source, cache_dir=None):
    folder = source_dir(source, cache_dir)
    result = {}
    for name, entry in source["files"].items():
        path = folder / name
        if not path.is_file():
            raise SourceError(f"Missing {source['id']} cache: run style-corpus prime")
        data = path.read_bytes()
        if sha(data) != entry["sha256"]:
            raise SourceError(f"Corrupt {source['id']} cache file: {name}")
        result[name] = data
    return result


def prime(cache_dir=None):
    for source in manifest()["supplemental"]:
        target = source_dir(source, cache_dir)
        try:
            verified_bytes(source, cache_dir)
            continue
        except SourceError:
            pass
        # Verify every remote byte before replacing any cached file.
        downloaded = {}
        for name, entry in source["files"].items():
            url = f"https://raw.githubusercontent.com/{source['repo']}/{source['pin']}/{entry['path']}"
            data = fetch(url)
            if sha(data) != entry["sha256"]:
                raise SourceError(f"Checksum mismatch: {source['id']}/{name}")
            downloaded[name] = data
        target.mkdir(parents=True, exist_ok=True)
        for name, data in downloaded.items():
            fd, tmp = tempfile.mkstemp(dir=target, prefix=".download-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.replace(tmp, target / name)
            finally:
                Path(tmp).unlink(missing_ok=True)
        verified_bytes(source, cache_dir)


def parse_markdown(text, source):
    records = []
    seen = set()
    for block in re.split(r"(?m)^### ", text)[1:]:
        if not re.search(r"(?im)(?:\*\*Prompt.*?\*\*|^#### .*Prompt)", block):
            continue
        prompts = re.findall(r"```[^\n]*\n(.*?)```", block, re.S)
        if not prompts:
            raise SourceError("Prompt marker without complete fenced prompt")
        title = block.split("\n", 1)[0].strip()
        if source["id"] == "youmind":
            ids = re.findall(r"youmind.com/gpt-image-2-prompts\?id=(\d+)", block)
            if len(set(ids)) != 1:
                raise SourceError(f"Missing or ambiguous stable gallery ID: {title}")
            ident = ids[0]
            title = re.sub(r"^No\. \d+:\s*", "", title)
        else:
            ident = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        ref = f"{source['id']}:{ident}"
        if ref in seen:
            raise SourceError(f"Duplicate source identity: {ref}")
        seen.add(ref)
        source_line = next((line for line in block.splitlines() if re.search(r"(?i)source\s*:?\*?\*?:?", line) and "http" in line), "")
        links = re.findall(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", source_line)
        original = links[0][1] if links else ""
        author_line = next((line for line in block.splitlines() if "**Author:**" in line), "")
        author_match = re.search(r"\[([^\]]+)\]", author_line)
        author = author_match.group(1) if author_match else (links[0][0] if links else "")
        prompt = "\n\n".join(p.strip() for p in prompts if p.strip())
        if not prompt:
            raise SourceError(f"Empty prompt: {ref}")
        records.append({"ref": ref, "title": title, "prompt": prompt,
                        "source_url": original, "author": author,
                        "repo_url": f"https://github.com/{source['repo']}/blob/{source['pin']}/README.md",
                        "prompt_sha256": sha(normal(prompt).encode()), "source": source["id"]})
    return records


def source_provenance(source):
    return {"id": source["id"], "repo": source["repo"], "pin": source["pin"],
            "sha256": source["files"]["README.md"]["sha256"],
            "license": source["license"], "license_url": source["license_url"]}


def load(cache_dir=None):
    policy = json.loads((HERE / "style-curation.json").read_text(encoding="utf-8"))
    decisions = policy["decisions"]
    included, catalog, sources = [], [], {}
    for source in manifest()["supplemental"]:
        data = verified_bytes(source, cache_dir)
        records = parse_markdown(data["README.md"].decode("utf-8"), source)
        if len(records) != source["expected_entries"]:
            raise SourceError(f"Unexpected entry count for {source['id']}: {len(records)}")
        sources[source["id"]] = source_provenance(source)
        for record in records:
            decision = decisions.get(record["ref"])
            if not decision or decision["prompt_sha256"] != record["prompt_sha256"]:
                raise SourceError(f"Missing or stale curation decision: {record['ref']}")
            record.update(decision)
            catalog.append(record)
            if decision["decision"] == "include":
                if not record["source_url"] or not record["author"]:
                    raise SourceError(f"Included case lacks attribution: {record['ref']}")
                included.append(record)
    actual_refs = {r["ref"] for r in catalog}
    if set(decisions) != actual_refs:
        raise SourceError("Curation and pinned source identities disagree")
    return included, catalog, sources


def tokens(text):
    text = normal(text)
    stop = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "image", "prompt", "create", "generate", "that", "this", "is", "as", "at", "by", "from", "no", "use"}
    words = [w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 1 and w not in stop]
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(run[i:i+2] for i in range(max(1, len(run)-1)))
    return set(words)


def lexical_scores(query, records):
    """Deterministic inverse-frequency term overlap; bilingual, no provider calls."""
    wanted = tokens(query)
    docs = {r["ref"]: tokens(" ".join([r["title"], r["prompt"], r.get("category", ""), " ".join(r.get("styles", [])), " ".join(r.get("scenes", []))])) for r in records}
    df = {term: sum(term in doc for doc in docs.values()) for term in wanted}
    return {ref: sum(math.log(1 + len(docs) / (1 + df[t])) for t in wanted & doc) for ref, doc in docs.items()}


def update_report(cache_dir=None):
    """Online comparison only. Verify baselines; never replace any pinned bytes."""
    report = []
    lock = manifest()
    for source in [lock["primary"]] + lock["supplemental"]:
        primary = source["id"] == "freestylefly"
        pin = source["active_pin"] if primary else source["pin"]
        spec = source["pins"][pin] if primary else source
        if primary:
            folder = cache_root(cache_dir) / "gpt-image-2-style-library" / pin
            baseline = {}
            for name, entry in spec["files"].items():
                path = folder / name
                if not path.is_file() or sha(path.read_bytes()) != entry["sha256"]:
                    raise SourceError(f"Missing or corrupt primary baseline: {name}")
                baseline[name] = path.read_bytes()
        else:
            baseline = verified_bytes(source, cache_dir)
        latest = json.loads(fetch(f"https://api.github.com/repos/{source['repo']}/commits/HEAD"))["sha"]
        fresh = {name: fetch(f"https://raw.githubusercontent.com/{source['repo']}/{latest}/{entry['path']}")
                 for name, entry in spec["files"].items()}
        if primary:
            olddata, newdata = json.loads(baseline["cases.json"]), json.loads(fresh["cases.json"])
            old, new = olddata["cases"], newdata["cases"]
            oldmap = {str(r["id"]): sha(normal(r["prompt"]).encode()) for r in old}
            newmap = {str(r["id"]): sha(normal(r["prompt"]).encode()) for r in new}
            def metadata(data):
                return {str(r["id"]): {k:v for k,v in r.items() if k != "prompt"} for r in data}
            metadata_changed = metadata(old) != metadata(new)
            envelope_changed = {k:v for k,v in olddata.items() if k != "cases"} != {k:v for k,v in newdata.items() if k != "cases"}
        else:
            old = parse_markdown(baseline["README.md"].decode("utf-8"), source)
            new = parse_markdown(fresh["README.md"].decode("utf-8"), source)
            oldmap = {r["ref"]:r["prompt_sha256"] for r in old}
            newmap = {r["ref"]:r["prompt_sha256"] for r in new}
            metadata_changed = [{k:v for k,v in r.items() if k not in {"prompt", "prompt_sha256"}} for r in old] != [{k:v for k,v in r.items() if k not in {"prompt", "prompt_sha256"}} for r in new]
            envelope_changed = baseline["README.md"] != fresh["README.md"] and old == new
        added = sorted(newmap.keys() - oldmap.keys())
        removed = sorted(oldmap.keys() - newmap.keys())
        changed = sorted(k for k in oldmap.keys() & newmap.keys() if oldmap[k] != newmap[k])
        changed_files = sorted(name for name in baseline if baseline[name] != fresh[name])
        report.append({"source":source["id"], "pinned":pin, "latest":latest,
                       "added":added, "removed":removed, "changed_prompts":changed,
                       "changed_files":changed_files,
                       "license_changed":"LICENSE" in changed_files,
                       "templates_changed":any(n in changed_files for n in ("templates.md", "style-library.json")),
                       "entry_metadata_changed":metadata_changed,
                       "document_or_timestamp_changes":envelope_changed,
                       "non_prompt_changes_only":bool(changed_files) and not (added or removed or changed),
                       "activated":False})
    return report
