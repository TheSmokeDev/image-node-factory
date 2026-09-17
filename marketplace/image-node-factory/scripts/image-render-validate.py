#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10,<13"]
# ///
"""Deterministic geometry gate for Image Node Factory render artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image


RATIO_TOLERANCE = 0.003


def _target_ratio(value: str) -> float | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:xX]\s*(\d+(?:\.\d+)?)\s*", value)
    if not match:
        return None
    width, height = (float(part) for part in match.groups())
    if width <= 0 or height <= 0:
        return None
    return width / height


def validate_render(artifacts_dir: Path) -> dict:
    brief_path = artifacts_dir / "image-node-brief.json"
    manifest_path = artifacts_dir / "images" / "manifest.json"
    if not brief_path.is_file() or not manifest_path.is_file():
        raise ValueError("missing image-node-brief.json or images/manifest.json")

    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    status = manifest.get("status")
    aspect = str(brief.get("aspect") or "")

    if status == "prompt_pack_only":
        return {"render_valid": True, "status": status, "image_count": 0, "aspect": aspect}
    if status == "blocked":
        if not (artifacts_dir / "render-blocked.md").is_file():
            raise ValueError("blocked render is missing render-blocked.md")
        return {"render_valid": True, "status": status, "image_count": 0, "aspect": aspect}
    if status != "rendered":
        raise ValueError(f"render is not terminal: {status!r}")

    images = manifest.get("images")
    expected_count = int(manifest.get("expected_count") or 0)
    if expected_count < 1 or not isinstance(images, list) or len(images) != expected_count:
        raise ValueError("manifest image count does not match expected_count")

    target = _target_ratio(aspect)
    checked = []
    seen_paths, seen_hashes = set(), set()
    for entry in images:
        filename = entry.get("filename")
        if not filename:
            raise ValueError("manifest image entry is missing filename")
        root = (artifacts_dir / "images").resolve()
        path = (root / filename).resolve()
        if path.parent != root or path in seen_paths:
            raise ValueError("manifest must reference distinct files inside images")
        seen_paths.add(path)
        if not path.is_file():
            raise ValueError(f"rendered image is missing: {filename}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if entry.get("sha256") != digest:
            raise ValueError(f"manifest hash disagrees with file: {filename}")
        if digest in seen_hashes:
            raise ValueError("duplicate image hashes detected")
        seen_hashes.add(digest)
        with Image.open(path) as image:
            width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError(f"invalid image dimensions: {filename}")
        actual = width / height
        if target is not None and abs(actual - target) > RATIO_TOLERANCE:
            raise ValueError(
                f"aspect mismatch for {filename}: requested {aspect}, got {width}x{height}"
            )
        if entry.get("width") not in (None, width) or entry.get("height") not in (None, height):
            raise ValueError(f"manifest dimensions disagree with file: {filename}")
        checked.append({"filename": filename, "width": width, "height": height})

    return {
        "render_valid": True,
        "status": status,
        "image_count": len(checked),
        "aspect": aspect,
        "images": checked,
    }


def main() -> int:
    raw = os.environ.get("ARTIFACTS_DIR", "").strip()
    if not raw:
        print(json.dumps({"render_valid": False, "error": "ARTIFACTS_DIR is required"}))
        return 1
    try:
        result = validate_render(Path(raw))
    except Exception as exc:
        print(json.dumps({"render_valid": False, "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
