import io

import pytest
from PIL import Image

from src.processor.image_utils import (
    MAX_FILE_BYTES,
    MAX_SIDE_PX,
    ImageValidationError,
    validate_image,
)


def make_bytes(fmt, size=(100, 100)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 50, 50)).save(buf, fmt)
    return buf.getvalue()


def test_accepts_jpeg():
    assert validate_image(make_bytes("JPEG")) == "JPEG"


def test_accepts_png():
    assert validate_image(make_bytes("PNG")) == "PNG"


def test_rejects_gif():
    with pytest.raises(ImageValidationError):
        validate_image(make_bytes("GIF"))


def test_rejects_text_file():
    with pytest.raises(ImageValidationError):
        validate_image(b"this is not an image")


def test_rejects_empty_file():
    with pytest.raises(ImageValidationError):
        validate_image(b"")


def test_rejects_file_over_size_limit():
    with pytest.raises(ImageValidationError):
        validate_image(b"x" * (MAX_FILE_BYTES + 1))


def test_rejects_image_with_huge_dimensions():
    with pytest.raises(ImageValidationError):
        validate_image(make_bytes("PNG", (MAX_SIDE_PX + 1, 10)))