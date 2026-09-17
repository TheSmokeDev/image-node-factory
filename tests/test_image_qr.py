from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "marketplace/image-node-factory"
SCRIPT = ROOT / "scripts" / "image-qr.py"
SPEC = spec_from_file_location("image_qr", SCRIPT)
assert SPEC and SPEC.loader
IMAGE_QR = module_from_spec(SPEC)
SPEC.loader.exec_module(IMAGE_QR)


@pytest.mark.parametrize(
    "url",
    (
        "https://example.com/lot/ABC-123",
        "https://example.com/coa?id=ABC-123",
    ),
)
def test_validate_https_url_preserves_exact_approved_target(url: str):
    assert IMAGE_QR.validate_https_url(url) == url


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/lot/1",
        "https://user:password@example.com/lot/1",
        "https://example.com/bad path",
        "not-a-url",
    ),
)
def test_validate_https_url_rejects_unsafe_or_ambiguous_targets(url: str):
    with pytest.raises(ValueError):
        IMAGE_QR.validate_https_url(url)


def test_parse_box_requires_non_negative_square_placement():
    assert IMAGE_QR.parse_box("80,960,220") == (80, 960, 220)
    with pytest.raises(Exception):
        IMAGE_QR.parse_box("80,-1,220")


def test_never_overwrite_source_or_existing_output(tmp_path: Path):
    source = tmp_path / "poster.png"
    source.write_bytes(b"source")
    with pytest.raises(ValueError):
        IMAGE_QR._ensure_new_output(source, source)
    output = tmp_path / "poster-v2.png"
    output.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        IMAGE_QR._ensure_new_output(source, output)


def test_generate_compose_and_verify_real_qr(tmp_path):
    pytest.importorskip("qrcode")
    pytest.importorskip("zxingcpp")
    from PIL import Image
    url = "https://example.com/lot/A-123?batch=09"
    standalone = tmp_path / "qr.png"
    assert IMAGE_QR.generate_qr(url, standalone, 512)["decoded_values"] == [url]
    source = tmp_path / "poster.png"
    Image.new("RGB", (800, 1000), "white").save(source)
    output = tmp_path / "poster-v2.png"
    assert IMAGE_QR.compose_qr(source, output, url, (160, 400, 400))["decoded_values"] == [url]
    assert IMAGE_QR.verify_qr(output, url)["status"] == "pass"
    with pytest.raises(ValueError, match="exact expected URL"):
        IMAGE_QR.verify_qr(output, "https://example.com/wrong")
