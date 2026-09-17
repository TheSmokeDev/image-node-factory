#!/usr/bin/env python3
"""Generate, place, and machine-verify production QR codes for image assets.

This is a deterministic post-render tool. Generative models may reserve the
visual space around a QR, but they must never be trusted to draw the QR itself.

Runtime dependencies are intentionally isolated from the project environment:

    uv run --with "qrcode[pil]" --with zxing-cpp \
      .archon/scripts/image-qr.py <command> ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def validate_https_url(value: str) -> str:
    """Return a normalized exact URL or raise for unsafe/non-public targets."""
    if value != value.strip() or any(ch.isspace() for ch in value):
        raise ValueError("QR URL must not contain surrounding or embedded whitespace")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("QR URL must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("QR URL must not contain embedded credentials")
    return value


def parse_box(value: str) -> tuple[int, int, int]:
    """Parse an X,Y,SIZE pixel box used to place a square QR."""
    try:
        parts = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("box must be X,Y,SIZE in pixels") from exc
    if len(parts) != 3 or any(part < 0 for part in parts[:2]) or parts[2] <= 0:
        raise argparse.ArgumentTypeError("box must be non-negative X,Y and positive SIZE")
    return parts


def _dependencies() -> tuple[Any, Any, Any]:
    try:
        import qrcode
        import zxingcpp
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised by the operator command
        raise SystemExit(
            "missing QR runtime dependencies; run with: "
            "uv run --with 'qrcode[pil]' --with zxing-cpp "
            ".archon/scripts/image-qr.py ..."
        ) from exc
    return qrcode, zxingcpp, Image


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_new_output(source: Path | None, output: Path) -> None:
    if source is not None and source.resolve() == output.resolve():
        raise ValueError("output must be a new versioned file, never the source image")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)


def _make_qr(url: str, size: int):
    qrcode, _, Image = _dependencies()
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=1,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    grid = len(matrix)
    scale = size // grid
    if scale < 4:
        raise ValueError("QR target is too small for this URL at high error correction")
    used = grid * scale
    offset = (size - used) // 2
    image = Image.new("RGB", (size, size), "white")
    for row_index, row in enumerate(matrix):
        for column_index, enabled in enumerate(row):
            if enabled:
                left = offset + column_index * scale
                top = offset + row_index * scale
                image.paste("black", (left, top, left + scale, top + scale))
    return image


def _decoded_values(path: Path) -> list[str]:
    _, zxingcpp, Image = _dependencies()
    return [result.text for result in zxingcpp.read_barcodes(Image.open(path))]


def _write_verified(image, output: Path, expected_url: str) -> list[str]:
    suffix = output.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("output extension must be .png, .jpg, or .jpeg")

    temp_handle = tempfile.NamedTemporaryFile(
        prefix=".image-qr-", suffix=suffix, dir=output.parent, delete=False
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    try:
        save_kwargs: dict[str, Any] = {}
        if suffix in {".jpg", ".jpeg"}:
            save_kwargs = {"quality": 95, "subsampling": 0}
        image.save(temp_path, **save_kwargs)
        decoded = _decoded_values(temp_path)
        if expected_url not in decoded:
            raise ValueError(
                "final image failed exact QR decode verification; no deliverable was written"
            )
        os.replace(temp_path, output)
        return decoded
    finally:
        if temp_path.exists():
            temp_path.unlink()


def generate_qr(url: str, output: Path, size: int) -> dict[str, Any]:
    url = validate_https_url(url)
    if size < 256:
        raise ValueError("standalone QR size must be at least 256 pixels")
    _ensure_new_output(None, output)
    image = _make_qr(url, size)
    decoded = _write_verified(image, output, url)
    return {
        "status": "pass",
        "operation": "generate",
        "output": str(output),
        "expected_url": url,
        "decoded_values": decoded,
        "size": [size, size],
        "sha256": _sha256(output),
    }


def compose_qr(source: Path, output: Path, url: str, box: tuple[int, int, int]) -> dict[str, Any]:
    url = validate_https_url(url)
    if not source.is_file():
        raise FileNotFoundError(f"source image not found: {source}")
    _ensure_new_output(source, output)
    _, _, Image = _dependencies()
    poster = Image.open(source).convert("RGB")
    x, y, size = box
    if size < 160:
        raise ValueError("composed QR must be at least 160 pixels")
    if x + size > poster.width or y + size > poster.height:
        raise ValueError("QR box extends beyond the source canvas")
    poster.paste(_make_qr(url, size), (x, y))
    decoded = _write_verified(poster, output, url)
    return {
        "status": "pass",
        "operation": "compose",
        "source": str(source),
        "output": str(output),
        "expected_url": url,
        "decoded_values": decoded,
        "box": [x, y, size],
        "canvas": [poster.width, poster.height],
        "sha256": _sha256(output),
    }


def verify_qr(image_path: Path, expected_url: str) -> dict[str, Any]:
    expected_url = validate_https_url(expected_url)
    if not image_path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    decoded = _decoded_values(image_path)
    if expected_url not in decoded:
        raise ValueError("image does not decode to the exact expected URL")
    return {
        "status": "pass",
        "operation": "verify",
        "image": str(image_path),
        "expected_url": expected_url,
        "decoded_values": decoded,
        "sha256": _sha256(image_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="write a standalone verified QR PNG/JPEG")
    generate.add_argument("--url", required=True)
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--size", type=int, default=1024)

    compose = subparsers.add_parser("compose", help="place and verify a QR on a versioned image")
    compose.add_argument("--input", required=True, type=Path)
    compose.add_argument("--output", required=True, type=Path)
    compose.add_argument("--url", required=True)
    compose.add_argument("--box", required=True, type=parse_box, metavar="X,Y,SIZE")

    verify = subparsers.add_parser("verify", help="decode an image and match the exact URL")
    verify.add_argument("--image", required=True, type=Path)
    verify.add_argument("--expected-url", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "generate":
            receipt = generate_qr(args.url, args.output, args.size)
        elif args.command == "compose":
            receipt = compose_qr(args.input, args.output, args.url, args.box)
        else:
            receipt = verify_qr(args.image, args.expected_url)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
