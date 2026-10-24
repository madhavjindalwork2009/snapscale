"""Build the processor Lambda package with Linux wheels (no Docker needed)."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "build" / "processor"

if OUT.parent.exists():
    shutil.rmtree(OUT.parent)
OUT.mkdir(parents=True)

for name in ("app.py", "image_utils.py"):
    shutil.copy(ROOT / "src" / "processor" / name, OUT / name)

subprocess.check_call([
    sys.executable, "-m", "pip", "install",
    "--platform", "manylinux_2_28_x86_64",
    "--platform", "manylinux2014_x86_64",
    "--implementation", "cp",
    "--python-version", "3.13",
    "--only-binary=:all:",
    "--upgrade",
    "--target", str(OUT),
    "pillow==13.0.0",
])
print("Built", OUT)