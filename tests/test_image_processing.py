import io
import os

import pytest
from PIL import Image

from src.processor.image_utils import VARIANTS, ImageValidationError, process_image


def make_bytes(fmt, size, mode="RGB", exif=None):
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    Image.new(mode, size, (30, 120, 200)).save(buf, fmt, **kwargs)
    return buf.getvalue()


def test_creates_three_variants_within_limits():
    result = process_image(make_bytes("JPEG", (3000, 2000)))
    assert set(result["variants"]) == {"thumbnail", "medium", "large"}
    for name, (limit, _) in VARIANTS.items():
        v = result["variants"][name]
        assert max(v["width"], v["height"]) == limit


def test_small_image_is_not_upscaled():
    result = process_image(make_bytes("JPEG", (100, 80)))
    for v in result["variants"].values():
        assert (v["width"], v["height"]) == (100, 80)


def test_png_stays_png():
    result = process_image(make_bytes("PNG", (500, 500), mode="RGBA"))
    for v in result["variants"].values():
        assert Image.open(io.BytesIO(v["data"])).format == "PNG"


def test_reported_sizes_match_real_files():
    result = process_image(make_bytes("JPEG", (1200, 900)))
    for v in result["variants"].values():
        img = Image.open(io.BytesIO(v["data"]))
        assert img.size == (v["width"], v["height"])
        assert len(v["data"]) == v["size_bytes"]


def test_exif_removed_and_orientation_applied():
    exif = Image.Exif()
    exif[0x0112] = 6               # orientation: rotate 90 degrees
    exif[0x010F] = "TestCamera"    # camera make
    original = make_bytes("JPEG", (400, 200), exif=exif)
    assert len(Image.open(io.BytesIO(original)).getexif()) > 0

    result = process_image(original)
    thumb = result["variants"]["thumbnail"]
    assert (thumb["width"], thumb["height"]) == (75, 150)  # rotated upright
    assert len(Image.open(io.BytesIO(thumb["data"])).getexif()) == 0


def test_rejects_corrupt_png():
    noise = Image.frombytes("RGB", (200, 200), os.urandom(200 * 200 * 3))
    buf = io.BytesIO()
    noise.save(buf, "PNG")
    broken = buf.getvalue()[: len(buf.getvalue()) // 2]
    with pytest.raises(ImageValidationError):
        process_image(broken)