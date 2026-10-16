"""Builds StepCap for handing out:
  dist/StepCap/                    the app, frozen by PyInstaller (StepCap.exe + its files)
  dist/StepCap-Setup-<version>.exe the installer (Inno Setup 6, when it is installed)

Setup once:  .venv/Scripts/python.exe -m pip install -r requirements-build.txt
             winget install --id JRSoftware.InnoSetup --scope user
Run:         .venv/Scripts/python.exe build.py
The frozen app runs its own --selfcheck before the installer is made; a
build never touches Documents\\StepCap (a temp storage stands in).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST, BUILD = HERE / "dist", HERE / "build"
EXE = DIST / "StepCap" / "StepCap.exe"
VERSION = re.search(r'^VERSION = "([^"]+)"', (HERE / "app.py").read_text(encoding="utf-8"), re.M).group(1)
DATA = ("ui", "samples/getting-started", "samples/getting-started-en")


def icon() -> Path:
    """build/StepCap.ico: the same orange icon the app draws for its window."""
    os.environ["STEPCAP_STORAGE"] = tempfile.mkdtemp(prefix="stepcap-build-")
    sys.path.insert(0, str(HERE))
    import app
    BUILD.mkdir(exist_ok=True)
    f = BUILD / "StepCap.ico"
    f.unlink(missing_ok=True)
    assert app.ensure_app_icon(f), "icon not written"
    shutil.rmtree(os.environ["STEPCAP_STORAGE"], ignore_errors=True)
    return f


def freeze() -> Path:
    import PyInstaller.__main__
    ico = icon()
    PyInstaller.__main__.run([
        "--noconfirm", "--clean", "--windowed", "--name", "StepCap", f"--icon={ico}",
        f"--distpath={DIST}", f"--workpath={BUILD / 'pyi'}", f"--specpath={BUILD}",
        "--hidden-import=pystray._win32", "--collect-submodules=winrt",
        *(f"--add-data={HERE / p}{os.pathsep}{p}" for p in DATA),
        str(HERE / "app.py")])
    return EXE


def selfcheck(exe: Path) -> dict:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "check.json"
        r = subprocess.run([str(exe), "--selfcheck", str(out)], timeout=180,
                           env={**os.environ, "STEPCAP_STORAGE": str(Path(d) / "st")})
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    if r.returncode or not got:
        raise SystemExit(f"self-check of {exe} failed: {got or r.returncode}")
    return got


def iscc() -> Path | None:
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        f = Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe" if base == os.environ.get("LOCALAPPDATA") \
            else Path(base) / "Inno Setup 6" / "ISCC.exe"
        if base and f.is_file():
            return f
    return None


def installer() -> Path:
    raise NotImplementedError  # Task 3


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    exe = freeze()
    print("self-check:", selfcheck(exe))
    if iscc():
        print("installer:", installer())
    else:
        print("Inno Setup 6 not found: made dist/StepCap/ only (winget install --id JRSoftware.InnoSetup --scope user)")
