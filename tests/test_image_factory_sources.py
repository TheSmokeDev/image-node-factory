"""Source identity, complete-example retrieval and v2 provenance regressions."""
import dataclasses
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "marketplace/image-node-factory/scripts"
sys.path.insert(0, str(SCRIPTS))
import style_sources as ss


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


sc = module("refresh_corpus", "style-corpus.py")
pv = module("refresh_validator", "pack-validate.py")


def case(cid=1, text="studio product photography", **kw):
    return sc.Case(cid, "Product", text, "Products & E-commerce", (), (), False,
                   "https://example.invalid/post/1", **kw)


def corpus(tmp_path, cases=None, extras=None):
    ym = next(s for s in ss.manifest()["supplemental"] if s["id"] == "youmind")
    return sc.Corpus(tmp_path, sc.UPSTREAM_PIN, cases or {1:case()}, {}, extras or {},
                     {"youmind":ss.source_provenance(ym)})


def markdown(number=1, prompt="A professional studio product photograph."):
    return f'''### No. {number}: Product
#### Prompt
```
{prompt}
```
- **Author:** [Artist](https://x.com/artist)
- **Source:** [Post](https://x.com/artist/status/123#reversed-0)
[Try it](https://youmind.com/gpt-image-2-prompts?id=456)
'''


def test_gallery_id_is_stable_when_readme_number_changes():
    source={"id":"youmind", "repo":"example/library", "pin":"pin"}
    a=ss.parse_markdown(markdown(1),source)[0]
    b=ss.parse_markdown(markdown(99),source)[0]
    assert a["ref"]==b["ref"]=="youmind:456"
    assert a["title"]==b["title"] and a["author"]=="Artist"


def test_parser_fails_on_identity_collision_or_incomplete_fence():
    source={"id":"youmind", "repo":"example/library", "pin":"pin"}
    with pytest.raises(ss.SourceError,match="Duplicate"):
        ss.parse_markdown(markdown()+markdown(2),source)
    with pytest.raises(ss.SourceError,match="complete fenced"):
        ss.parse_markdown("### Broken\n#### Prompt\n```\npartial",source)


def test_unknown_pin_is_not_a_checksum_bypass(tmp_path):
    folder=tmp_path/sc.SKILL_NAME/"unknown"; folder.mkdir(parents=True)
    with pytest.raises(sc.CorpusMissing,match="unregistered"):
        sc.require_corpus(pin="unknown",cache_dir=tmp_path)
    with pytest.raises(sc.CorpusMissing,match="unregistered"):
        sc.prime(pin="unknown",cache_dir=tmp_path)


def test_rollback_pin_hashes_are_enforced(tmp_path):
    old=next(p for p in sc.PINNED_FILES if p!=sc.UPSTREAM_PIN)
    folder=tmp_path/sc.SKILL_NAME/old; folder.mkdir(parents=True)
    for name in sc.PINNED_FILES[old]: (folder/name).write_text("corrupt")
    with pytest.raises(sc.CorpusMissing,match="corrupt file"):
        sc.require_corpus(pin=old,cache_dir=tmp_path)


def test_secondary_corruption_cannot_be_blessed_by_marker(tmp_path):
    source=ss.manifest()["supplemental"][0]
    folder=ss.source_dir(source,tmp_path); folder.mkdir(parents=True)
    for name in source["files"]: (folder/name).write_text("corrupt")
    (folder/".ok").write_text("verified")
    with pytest.raises(ss.SourceError,match="Corrupt"):
        ss.verified_bytes(source,tmp_path)


def test_complete_examples_skip_oversize_and_fill_budget(tmp_path,monkeypatch):
    c=corpus(tmp_path,{1:case(1,"x"*90),2:case(2,"short complete")})
    monkeypatch.setattr(sc,"_EXEMPLAR_TOTAL_BUDGET",40)
    g=sc.select(c,case_ids=[1,2])
    assert g.resolved_case_ids==(2,) and g.exemplars[0].prompt=="short complete"
    assert not g.exemplars[0].truncated
    assert g.excluded[0]["ref"]=="freestylefly:1"


def test_new_cases_are_discoverable_without_template_anchor(tmp_path):
    c=corpus(tmp_path,{1:case(1,"generic studio"),532:case(532,"lemon miniature campaign six panel beverage")})
    rows=sc.candidate_catalog(c,"lemon miniature beverage campaign")
    assert rows[0]["ref"]=="freestylefly:532"


def test_exact_duplicates_have_aliases_but_shared_article_is_not_collapsed(tmp_path):
    c=corpus(tmp_path,{1:case(1,"studio apple"),2:case(2,"  studio APPLE "),3:case(3,"studio pear")})
    g=sc.select(c,query="studio",k=5)
    assert len(g.exemplars)==2
    assert any(v for v in g.provenance["aliases"].values())
    assert len(sc.candidate_catalog(c,"studio"))==2


def write_pack(tmp_path,g):
    payload=g.full()
    (tmp_path/"image-node-grounding.local.json").write_text(json.dumps(payload),encoding="utf-8")
    (tmp_path/"image-node-brief.json").write_text(json.dumps({"count":1}),encoding="utf-8")
    pack={**g.provenance,"example_case_refs":payload["resolved_case_refs"],
          "example_case_ids":list(g.resolved_case_ids),"prompt_count":1,
          "concepts":[{"baked_prompt":"Original wording","overlay_prompt":"Text-free original","copy":{}}]}
    path=tmp_path/"image-node-prompt-pack.json"; path.write_text(json.dumps(pack),encoding="utf-8")
    return path,pack


def test_mixed_license_pack_and_legacy_integer_references(tmp_path):
    extra=case(0,"natural window headshot",ref="youmind:34675",source="youmind",author="Artist")
    c=corpus(tmp_path,extras={extra.ref:extra})
    g=sc.select(c,case_ids=[1],case_refs=[extra.ref],k=2)
    assert g.resolved_case_ids==(1,)
    assert g.provenance["license"]=="MIXED"
    path,pack=write_pack(tmp_path,g)
    assert pv.validate_pack(tmp_path)["pack_valid"]
    pack["license"]="MIT"; path.write_text(json.dumps(pack))
    with pytest.raises(pv.PackInvalid,match="license"):
        pv.validate_pack(tmp_path)


@pytest.mark.parametrize("key,value",[("schema_version",1),("sources",[]),("citations",[]),("example_case_refs",["youmind:999"]),("example_case_ids",[99])])
def test_v2_cannot_drop_or_forge_provenance(tmp_path,key,value):
    g=sc.select(corpus(tmp_path),case_ids=[1]); path,pack=write_pack(tmp_path,g)
    pack[key]=value; path.write_text(json.dumps(pack))
    with pytest.raises(pv.PackInvalid): pv.validate_pack(tmp_path)


def test_zero_matches_have_no_source_claims(tmp_path):
    g=sc.select(corpus(tmp_path),query="unrelated-zzzz")
    assert not g.grounded and g.provenance=={}


def test_active_real_bundle_when_provisioned():
    try: c=sc.require_corpus()
    except sc.CorpusMissing: pytest.skip("source cache not provisioned")
    assert len(c.cases)==541 and len(c.templates)==22 and len(c.supplemental)==13
    _,catalog,_=ss.load()
    assert len(catalog)==198 and all(r["reason"] for r in catalog)
    assert sc.select(c,case_ids=[532]).exemplars[0].prompt==c.cases[532].prompt
    assert sc.candidate_catalog(c,"natural approachable professional headshot reference identity")[0]["ref"]=="youmind:34675"

def test_category_keeps_driver_photographs_out_of_electronics(tmp_path):
    electronics = case(1, "LED driver driver driver electronic circuit")
    portrait = dataclasses.replace(case(2, "natural daylight photograph person"), category="Realistic Photography")
    c = corpus(tmp_path, {1:electronics, 2:portrait})
    rows = sc.candidate_catalog(c, "driver photograph", "Realistic Photography")
    assert [r["ref"] for r in rows] == ["freestylefly:2"]
    assert sc.select(c, query="driver photograph", category="Realistic Photography").resolved_case_ids == (2,)


def test_update_report_checks_primary_bytes_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "fetch", lambda _: pytest.fail("corrupt baseline must fail before networking"))
    with pytest.raises(ss.SourceError, match="primary baseline"):
        ss.update_report(tmp_path)


def test_update_report_separates_prompts_templates_and_metadata(tmp_path, monkeypatch):
    data = {"updated_at":"old", "cases":[{"id":1,"prompt":"complete example"}]}
    raw = json.dumps(data).encode()
    files = {"cases.json":raw, "templates.md":b"template", "LICENSE":b"notice"}
    source = {"id":"freestylefly", "repo":"owner/repo", "active_pin":"old",
              "pins":{"old":{"files":{name:{"path":name,"sha256":ss.sha(body)} for name,body in files.items()}}}}
    folder = tmp_path / "gpt-image-2-style-library" / "old"
    folder.mkdir(parents=True)
    for name,body in files.items(): (folder/name).write_bytes(body)
    fresh = {**files, "cases.json":json.dumps({**data,"updated_at":"new"}).encode(), "templates.md":b"new template"}
    monkeypatch.setattr(ss,"manifest",lambda:{"primary":source,"supplemental":[]})
    monkeypatch.setattr(ss,"fetch",lambda url: b'{"sha":"new"}' if "api.github" in url else fresh[url.rsplit("/",1)[1]])
    row = ss.update_report(tmp_path)[0]
    assert row["changed_prompts"] == [] and row["templates_changed"]
    assert row["document_or_timestamp_changes"] and row["non_prompt_changes_only"]
    assert not row["license_changed"] and not row["activated"]
    assert (folder/"cases.json").read_bytes() == raw


def test_active_index_preserves_duplicate_aliases_and_shared_articles(tmp_path):
    c=corpus(tmp_path,{1:case(1,"studio apple"),2:case(2,"studio APPLE"),3:case(3,"studio pear")})
    index=sc.active_index(c)
    assert index["record_count"]==3 and index["unique_prompt_count"]==2
    assert index["cases"][0]["aliases"]==["freestylefly:2"]
    assert list(index["shared_source_links"].values())==[["freestylefly:1","freestylefly:2","freestylefly:3"]]
