from pathlib import Path

from src.processor.image_utils import ImageValidationError, process_image

SAMPLES = Path("samples")
OUT = SAMPLES / "output"


def main():
    OUT.mkdir(exist_ok=True)
    files = [p for p in SAMPLES.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if not files:
        print("Put a JPEG or PNG file in the samples folder first.")
        return
    for path in files:
        data = path.read_bytes()
        try:
            result = process_image(data)
        except ImageValidationError as exc:
            print(f"REJECTED {path.name}: {exc}")
            continue
        o = result["original"]
        print(f"{path.name}: {o['width']}x{o['height']}, {len(data):,} bytes")
        for name, v in result["variants"].items():
            out = OUT / f"{path.stem}_{name}{v['extension']}"
            out.write_bytes(v["data"])
            saving = (1 - v["size_bytes"] / len(data)) * 100
            print(f"  {name:<9} {v['width']}x{v['height']}  {v['size_bytes']:,} bytes  ({saving:.1f}% smaller)")


main()