"""The real installer, installed and removed again on THIS computer. Run by
hand only, once before handing a build out, after telling the user:
  python build.py && python test_installer.py
What it touches, all undone by the uninstall at the end:
  - a temp folder under %LOCALAPPDATA% (the install dir)
  - the Start menu shortcut StepCap.lnk and the "Apps" uninstall entry (per user)
It never creates a desktop icon (/TASKS=), never opens StepCap's window
(silent setup skips "Open StepCap"), and only reads Documents\\StepCap.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = re.search(r'^VERSION = "([^"]+)"', (HERE / "app.py").read_text(encoding="utf-8"), re.M).group(1)
SETUP = HERE / "dist" / f"StepCap-Setup-{VERSION}.exe"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "StepCap.lnk"
DOCS = Path.home() / "Documents" / "StepCap"


def _snapshot(root: Path) -> dict:
    """path -> (size, mtime) of the user's guides; the app's own run files left out."""
    if not root.is_dir():
        return {}
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file() and p.name != "_run.json" and "_tmp" not in p.parts}


def _setup(lang: str, target: Path):
    r = subprocess.run([str(SETUP), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        f"/LANG={lang}", "/TASKS=", f"/DIR={target}"], timeout=300)
    assert r.returncode == 0, f"setup exit {r.returncode}"


def test_install_run_uninstall():
    assert SETUP.is_file(), f"no {SETUP}: run build.py first"
    assert not SHORTCUT.exists(), "a StepCap shortcut is already there: is StepCap installed? not touching it"
    before = _snapshot(DOCS)
    target = Path(tempfile.mkdtemp(prefix="StepCap test ", dir=os.environ["LOCALAPPDATA"]))
    try:
        _setup("en", target)
        assert (target / "StepCap.exe").is_file()
        assert (target / "lang.txt").read_text().strip() == "en"
        assert SHORTCUT.is_file()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "check.json"
            r = subprocess.run([str(target / "StepCap.exe"), "--selfcheck", str(out)], timeout=180,
                               env={**os.environ, "STEPCAP_STORAGE": str(Path(d) / "st")})
            got = json.loads(out.read_text(encoding="utf-8"))
            assert r.returncode == 0 and all(v == "ok" for v in got.values()), got
        _setup("th", target)  # an update over it, picked in Thai this time
        assert (target / "lang.txt").read_text().strip() == "th"
        subprocess.run([str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                       timeout=300)
        end = time.time() + 60  # the uninstaller finishes from a copy of itself
        while time.time() < end and ((target / "StepCap.exe").exists() or SHORTCUT.exists()):
            time.sleep(0.5)
        assert not (target / "StepCap.exe").exists() and not (target / "lang.txt").exists()
        assert not SHORTCUT.exists()
    finally:
        shutil.rmtree(target, ignore_errors=True)
    assert _snapshot(DOCS) == before, "Documents\\StepCap changed"


if __name__ == "__main__":
    import traceback
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        test_install_run_uninstall()
        print("ok   test_install_run_uninstall\n\n1/1 passed")
    except Exception:
        print("FAIL test_install_run_uninstall")
        traceback.print_exc()
        print("\n0/1 passed")
        raise SystemExit(1)
