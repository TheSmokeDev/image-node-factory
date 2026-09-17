"""Portable package contracts: all DAG references resolve inside this tree."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "marketplace/image-node-factory"


def test_packaged_files_have_exact_digests():
    manifest = json.loads((ROOT / "package-manifest.json").read_text())
    for relative, digest in manifest["files"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def test_portable_dag_has_no_missing_scripts_or_commands():
    workflow = yaml.safe_load((PACKAGE / "image-node-factory.yaml").read_text())
    ids = {node["id"] for node in workflow["nodes"]}
    for node in workflow["nodes"]:
        assert set(node.get("depends_on", [])) <= ids
        for key, folder, suffix in (("script", "scripts", ".py"), ("command", "commands", ".md")):
            if key in node:
                assert (PACKAGE / folder / (node[key] + suffix)).is_file()
    render = next(n for n in workflow["nodes"] if n["id"] == "render")
    assert render["command"] == "image-node-render" and "script" not in render
    assert "render-gate-check" in render["depends_on"]


def test_source_module_imports_from_this_package():
    sys.path.insert(0, str(PACKAGE / "scripts"))
    import style_sources
    assert Path(style_sources.__file__).resolve().parent == (PACKAGE / "scripts").resolve()
