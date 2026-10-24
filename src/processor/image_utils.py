"""Image validation and processing for SnapScale."""
import io

from PIL import Image, ImageOps

MAX_FILE_BYTES = 10 * 1024 * 1024      # 10 MB
MAX_SIDE_PX = 8000                     # longest allowed side
MAX_TOTAL_PIXELS = 40_000_000          # width x height limit
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png"}
VARIANTS = {
    "thumbnail": (150, 150),
    "medium": (800, 800),
    "large": (1600, 1600),
}
JPEG_QUALITY = 80


class ImageValidationError(Exception):
    """Raised when an uploaded file is not an acceptable image."""


def validate_image(data: bytes) -> str:
    """Check the file is a safe JPEG or PNG. Returns 'JPEG' or 'PNG'."""
    if not data:
        raise ImageValidationError("File is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ImageValidationError("File is larger than 10 MB")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            width, height = img.size
            if fmt not in ALLOWED_FORMATS:
                raise ImageValidationError(f"Unsupported format: {fmt}")
            if max(width, height) > MAX_SIDE_PX:
                raise ImageValidationError("Image dimensions are too large")
            if width * height > MAX_TOTAL_PIXELS:
                raise ImageValidationError("Image has too many pixels")
            img.verify()
    except ImageValidationError:
        raise
    except Exception as exc:
        raise ImageValidationError("File is not a valid image") from exc
    return fmt


def _prepare_mode(img: Image.Image, fmt: str) -> Image.Image:
    """Convert colour modes that cannot be saved or resized cleanly."""
    if fmt == "JPEG":
        return img if img.mode in ("RGB", "L") else img.convert("RGB")
    return img if img.mode in ("RGB", "RGBA", "L", "LA") else img.convert("RGBA")


def _encode(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    # No exif/icc arguments are passed, so metadata is not written out.
    if fmt == "JPEG":
        img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def process_image(data: bytes) -> dict:
    """Validate an image and create the three variants."""
    fmt = validate_image(data)
    try:
        with Image.open(io.BytesIO(data)) as original:
            oriented = ImageOps.exif_transpose(original)  # apply EXIF rotation
            oriented.load()
    except Exception as exc:
        raise ImageValidationError("Image could not be decoded") from exc

    base = _prepare_mode(oriented, fmt)
    result = {
        "format": fmt,
        "content_type": ALLOWED_FORMATS[fmt],
        "original": {
            "width": base.width,
            "height": base.height,
            "size_bytes": len(data),
        },
        "variants": {},
    }
    for name, box in VARIANTS.items():
        variant = base.copy()
        variant.thumbnail(box, Image.Resampling.LANCZOS)  # never upscales
        encoded = _encode(variant, fmt)
        result["variants"][name] = {
            "data": encoded,
            "width": variant.width,
            "height": variant.height,
            "size_bytes": len(encoded),
            "content_type": ALLOWED_FORMATS[fmt],
            "extension": EXTENSIONS[fmt],
        }
    return result