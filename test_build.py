"""Checks the frozen build in dist/StepCap/ (make it with: python build.py).
Runs StepCap.exe on a temp storage only; no clicks or keys anywhere.
Run: python test_build.py"""
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE = HERE / "dist" / "StepCap" / "StepCap.exe"


def _env(st: Path) -> dict:
    return {**os.environ, "STEPCAP_STORAGE": str(st)}


def test_frozen_selfcheck():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "check.json"
        r = subprocess.run([str(EXE), "--selfcheck", str(out)], env=_env(Path(d) / "st"), timeout=120)
        got = json.loads(out.read_text(encoding="utf-8"))
        assert r.returncode == 0 and all(v == "ok" for v in got.values()), got


def test_frozen_app_starts():
    import library
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        proc = subprocess.Popen([str(EXE)], env=_env(st))
        try:
            end = time.time() + 30
            while time.time() < end and not (st / "_run.json").exists():
                time.sleep(0.3)
            run = json.loads((st / "_run.json").read_text(encoding="utf-8"))
            base = f"http://127.0.0.1:{run['port']}"
            tok = "t=" + run["token"]

            def get(path):
                sep = "&" if "?" in path else "?"
                with urllib.request.urlopen(f"{base}{path}{sep}{tok}", timeout=15) as r:
                    return r.read().decode("utf-8")

            def post(path, body):
                req = urllib.request.Request(f"{base}{path}?{tok}", json.dumps(body).encode(),
                                             {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    return r.read()

            assert 'const LANG="' in get("/")
            titles = [g["title"] for g in json.loads(get("/api/guides"))]
            assert len(titles) == 1 and titles[0] in library.SAMPLE_TITLES.values(), titles
            post("/api/settings", {"lang": "en"})
            page = get("/")
            assert 'const LANG="en"' in page and '"Contents"' in page
        finally:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            proc.wait(15)
        pid = run["pid"]
        left = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        assert str(pid) not in left, left
        time.sleep(1)  # the folder is free once WebView2 lets go


def test_frozen_has_no_console():
    b = EXE.read_bytes()[:4096]
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    subsystem = struct.unpack_from("<H", b, pe + 4 + 20 + 68)[0]
    assert subsystem == 2, subsystem  # IMAGE_SUBSYSTEM_WINDOWS_GUI


if __name__ == "__main__":
    import traceback
    sys.stdout.reconfigure(encoding="utf-8")
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
