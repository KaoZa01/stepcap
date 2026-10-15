"""Page-level checks for the image editor, run in a pywebview window against a
launched StepCap on temp storage. Only DOM events inside StepCap's own page
are dispatched; nothing touches the real desktop. Windows only.
Run: python test_render.py"""
import base64
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from io import BytesIO
from pathlib import Path

import webview
from PIL import Image

HERE = Path(__file__).resolve().parent
CTX: dict = {}


def _noise() -> Image.Image:
    rnd = random.Random(7)
    img = Image.new("RGB", (320, 200))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(320 * 200)])
    return img


NOISE = _noise()
_b = BytesIO()
NOISE.save(_b, "PNG")
NOISE_PNG = _b.getvalue()

ORANGE, RED, BLUE = "#FB923C", "#EF4444", "#3B82F6"


def _guide(st: Path, gid: str, steps: list, **extra):
    folder = st / gid
    folder.mkdir()
    (folder / "n.png").write_bytes(NOISE_PNG)
    g = {"id": gid, "title": f"{gid} - test", "created": "2026-10-15T10:00:00",
         "steps": steps, **extra}
    (folder / "guide.json").write_text(json.dumps(g, ensure_ascii=False),
                                       encoding="utf-8")


def seed(st: Path):
    _guide(st, "noise", [
        {"id": "a1", "kind": "click", "text": "noise step", "image": "n.png",
         "crop": None,
         "markers": [{"x": 160, "y": 100, "color": ORANGE, "size": 44,
                      "shape": "rect"}],
         "annotations": [
             {"type": "box", "x": 10, "y": 120, "w": 80, "h": 50,
              "color": RED, "width": 8},
             {"type": "arrow", "x1": 150, "y1": 20, "x2": 250, "y2": 60,
              "color": BLUE, "width": 8}],
         "redactions": [{"type": "black", "x": 20, "y": 20, "w": 60, "h": 40},
                        {"type": "blur", "x": 200, "y": 100, "w": 80, "h": 60}]},
    ])
    _guide(st, "cropx", [
        {"id": "c1", "kind": "click", "text": "crop step", "image": "n.png",
         "crop": {"x": 100, "y": 50, "w": 150, "h": 100}, "markers": [],
         "redactions": [{"type": "black", "x": 220, "y": 120, "w": 80, "h": 60}]},
    ])
    _guide(st, "old", [  # pieces 0+1 shape: no shape, no layers, no click_shape
        {"id": "o1", "kind": "click", "text": "old step", "image": "n.png",
         "crop": None,
         "markers": [{"x": 50, "y": 50, "color": ORANGE, "size": 44}]},
    ], settings={"click_color": ORANGE})


def launch():
    st = Path(tempfile.mkdtemp(prefix="stepcap-render-"))
    CTX["storage"] = st
    seed(st)
    CTX["proc"] = subprocess.Popen(
        [sys.executable, "app.py"], cwd=HERE,
        env={**os.environ, "STEPCAP_STORAGE": str(st)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 20
    while time.time() < end and not (st / "_run.json").exists():
        time.sleep(0.2)
    run = json.loads((st / "_run.json").read_text(encoding="utf-8"))
    CTX["base"] = f"http://127.0.0.1:{run['port']}/?t={run['token']}"


def teardown():
    p = CTX.get("proc")
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       capture_output=True)
        p.wait(10)
    shutil.rmtree(CTX.get("storage", ""), ignore_errors=True)


_B64 = """window.__b64 = async blob => { const u = new Uint8Array(await blob.arrayBuffer());
  let s = ""; for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s); }; 1"""


def page(query: str):
    """Open StepCap's page in a fresh window (load_url breaks evaluate_js)."""
    old = CTX.pop("win", None)
    if old:
        old.destroy()
    w = webview.create_window("render-test", CTX["base"] + "&" + query,
                              width=1200, height=800, x=40, y=20)
    w.events.loaded.wait(20)
    time.sleep(2.5)
    w.evaluate_js(_B64)
    CTX["win"] = w
    return w


def js(body: str, timeout: float = 30):
    """Run an async JS function body in the current page; returns its value."""
    w = CTX["win"]
    w.evaluate_js("window.__r = undefined; (async () => { " + body + " })().then("
                  "v => { window.__r = {ok: v === undefined ? null : v}; },"
                  "e => { window.__r = {err: String(e && e.stack || e)}; }); 1")
    end = time.time() + timeout
    while time.time() < end:
        r = w.evaluate_js("window.__r === undefined ? null : window.__r")
        if r is not None:
            if "err" in r:
                raise AssertionError("JS error: " + r["err"])
            return r["ok"]
        time.sleep(0.1)
    raise TimeoutError(body[:80])


def png(b64: str) -> Image.Image:
    return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")


def _black(img, xs, ys):
    return all(img.getpixel((x, y)) == (0, 0, 0) for x in xs for y in ys)


# ---------------------------------------------------------------- tests
def test_bake_hides_pixels():
    page("guide=noise&mode=edit")
    img = png(js("return __b64(await renderStepPng(STATE.steps[0], GID));"))
    assert img.size == (320, 200)
    assert _black(img, range(20, 80), range(20, 60))
    same = sum(img.getpixel((x, y)) == NOISE.getpixel((x, y))
               for x in range(205, 275) for y in range(105, 155))
    assert same / (70 * 50) < 0.05, same  # blurred: originals gone
    assert img.getpixel((300, 10)) == NOISE.getpixel((300, 10))  # untouched


def test_export_contains_no_original():
    html = js("return await buildExportHtml(GID);")
    original = base64.b64encode(NOISE_PNG).decode()
    assert original[1000:1200] not in html
    data = json.loads(re.search(r"const guide=(.*?);\n", html, re.S).group(1))
    s = data["steps"][0]
    assert s["crop"] is None and s["markers"] == [] and s["annotations"] == []
    assert s["redactions"] == [] and "image" not in s
    assert s["_src"].startswith("data:image/png;base64,")
    img = png(s["_src"].split(",", 1)[1])
    assert _black(img, range(20, 80), range(20, 60))


def test_bake_redaction_across_crop():
    img = png(js("const g = await getJSON('/api/guide/cropx');"
                 "return __b64(await renderStepPng(g.steps[0], 'cropx'));"))
    assert img.size == (150, 100)
    assert _black(img, range(120, 150), range(70, 100))
    assert img.getpixel((5, 5)) == NOISE.getpixel((105, 55))


def test_old_guide_exports_flattened():
    html = js("return await buildExportHtml('old');")
    assert "data:image/png;base64," in html
    data = json.loads(re.search(r"const guide=(.*?);\n", html, re.S).group(1))
    assert data["steps"][0]["markers"] == []


TESTS = [test_bake_hides_pixels, test_export_contains_no_original,
         test_bake_redaction_across_crop, test_old_guide_exports_flattened]


def run_all(holder):
    try:
        for fn in TESTS:
            try:
                fn()
                CTX.setdefault("ok", []).append(fn.__name__)
                print(f"ok   {fn.__name__}", flush=True)
            except Exception:
                print(f"FAIL {fn.__name__}", flush=True)
                traceback.print_exc()
    finally:
        if CTX.get("win"):
            CTX["win"].destroy()
        holder.destroy()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        launch()
        holder = webview.create_window("holder", html="<p>.</p>", hidden=True)
        webview.start(run_all, (holder,), private_mode=True)
    finally:
        teardown()
    passed = len(CTX.get("ok", []))
    print(f"\n{passed}/{len(TESTS)} passed")
    raise SystemExit(0 if passed == len(TESTS) else 1)
