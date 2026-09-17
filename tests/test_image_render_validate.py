import importlib.util
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image


MODULE_PATH = Path(__file__).resolve().parents[1] / "marketplace/image-node-factory" / "scripts" / "image-render-validate.py"
SPEC = importlib.util.spec_from_file_location("image_render_validate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _rendered_fixture(tmp_path: Path, size=(1080, 1350)) -> Path:
    images = tmp_path / "images"
    images.mkdir()
    Image.new("RGB", size, "white").save(images / "asset-01.png")
    (tmp_path / "image-node-brief.json").write_text(
        json.dumps({"aspect": "4:5"}), encoding="utf-8"
    )
    (images / "manifest.json").write_text(
        json.dumps(
            {
                "status": "rendered",
                "expected_count": 1,
                "images": [
                    {
                        "filename": "asset-01.png",
                        "sha256": hashlib.sha256((images / "asset-01.png").read_bytes()).hexdigest(),
                        "width": size[0],
                        "height": size[1],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_accepts_true_four_by_five(tmp_path):
    result = MODULE.validate_render(_rendered_fixture(tmp_path))
    assert result["render_valid"] is True
    assert result["image_count"] == 1


def test_accepts_negligible_renderer_rounding(tmp_path):
    result = MODULE.validate_render(_rendered_fixture(tmp_path, (1122, 1402)))
    assert result["render_valid"] is True


def test_rejects_wrong_aspect(tmp_path):
    with pytest.raises(ValueError, match="aspect mismatch"):
        MODULE.validate_render(_rendered_fixture(tmp_path, (1003, 1568)))


def test_accepts_prompt_pack_only(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (tmp_path / "image-node-brief.json").write_text(
        json.dumps({"aspect": "4:5"}), encoding="utf-8"
    )
    (images / "manifest.json").write_text(
        json.dumps({"status": "prompt_pack_only", "images": []}), encoding="utf-8"
    )
    assert MODULE.validate_render(tmp_path)["status"] == "prompt_pack_only"


@pytest.mark.parametrize("mutation,match", [("hash","hash disagrees"),("duplicate","distinct files"),("escape","inside images"),("empty","count")])
def test_rejects_forged_or_duplicate_receipts(tmp_path, mutation, match):
    _rendered_fixture(tmp_path)
    path = tmp_path / "images/manifest.json"
    data = json.loads(path.read_text())
    if mutation == "hash": data["images"][0]["sha256"] = "0" * 64
    elif mutation == "duplicate":
        data["images"] *= 2
        data["expected_count"] = 2
    elif mutation == "escape": data["images"][0]["filename"] = "../outside.png"
    else:
        data["images"] = []
        data["expected_count"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=match): MODULE.validate_render(tmp_path)
