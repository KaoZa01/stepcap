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

def _pii_png() -> bytes:
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (640, 80), "white")
    ImageDraw.Draw(img).text((20, 20), "contact: someone@example.com", fill="black",
                             font=ImageFont.truetype("arial.ttf", 28))
    b = BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


PII_PNG = _pii_png()
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
    _guide(st, "pii", [{"id": "p1", "kind": "click", "text": "pii", "image": "p.png",
                        "crop": None, "markers": []}])
    (st / "pii" / "p.png").write_bytes(PII_PNG)
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
        {"id": "a2", "kind": "click", "text": "second", "image": "n.png",
         "crop": None,
         "markers": [{"x": 40, "y": 40, "color": ORANGE, "size": 44},
                     {"x": 90, "y": 90, "color": ORANGE, "size": 44}]},
        {"id": "a3", "kind": "image", "text": "a gif", "image": "g.gif",
         "crop": None, "markers": []},
    ])
    gif = BytesIO()
    Image.new("RGB", (40, 30), (255, 0, 0)).save(gif, "GIF")
    (st / "noise" / "g.gif").write_bytes(gif.getvalue())
    _guide(st, "broken", [
        {"id": "b1", "kind": "click", "text": "missing", "image": "missing.png",
         "crop": None, "markers": []},
        {"id": "b2", "kind": "click", "text": "junk", "image": "bad.png",
         "crop": None, "markers": []},
    ])
    (st / "broken" / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"junk" * 50)
    _guide(st, "cropx", [
        {"id": "c1", "kind": "click", "text": "crop step", "image": "n.png",
         "crop": {"x": 100, "y": 50, "w": 150, "h": 100}, "markers": [],
         "redactions": [{"type": "black", "x": 220, "y": 120, "w": 80, "h": 60}]},
    ])
    _guide(st, "edge", [
        {"id": "e1", "kind": "click", "text": "blur at the edges", "image": "n.png",
         "crop": None, "markers": [],
         "redactions": [{"type": "blur", "x": 0, "y": 0, "w": 100, "h": 30},
                        {"type": "blur", "x": 300, "y": 180, "w": 20, "h": 20}]},
        {"id": "e2", "kind": "click", "text": "blur over black", "image": "n.png",
         "crop": None, "markers": [],
         "redactions": [{"type": "black", "x": 120, "y": 80, "w": 60, "h": 30},
                        {"type": "blur", "x": 90, "y": 60, "w": 140, "h": 80}]},
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


def _png_js(name: str) -> str:
    small = BytesIO()
    Image.new("RGB", (4, 4), (0, 200, 0)).save(small, "PNG")
    b64 = base64.b64encode(small.getvalue()).decode()
    return (f"const u = Uint8Array.from(atob('{b64}'), c => c.charCodeAt(0));"
            f"const file = new File([u], '{name}', {{type: 'image/png'}});")


def test_click_style_all_markers():
    page("guide=noise&mode=edit")
    js("setClickStyle({shape: 'rect', size: 70});")
    ms = js("return STATE.steps.flatMap(s => s.markers);")
    assert len(ms) == 3 and all(m["shape"] == "rect" and m["size"] == 70 for m in ms)
    assert all(m["color"] == ORANGE for m in ms)  # only the patched keys change
    assert js("return STATE.settings.click_shape + STATE.settings.click_size;") == "rect70"
    assert {a["color"] for a in js("return STATE.steps[0].annotations;")} == {RED, BLUE}


def test_text_paste_ignored():
    n = js("return STATE.steps.length;")
    js("const dt = new DataTransfer(); dt.setData('text/plain', 'hi');"
       "document.body.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));")
    time.sleep(1.5)
    assert js("return STATE.steps.length;") == n


def test_image_paste_adds_step():
    n = js("return STATE.steps.length;")
    js(_png_js("p.png") + "const dt = new DataTransfer(); dt.items.add(file);"
       "document.body.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));")
    last = js("for (let i = 0; i < 60 && STATE.steps.length === " + str(n) + "; i++)"
              "  await new Promise(r => setTimeout(r, 50));"
              "return STATE.steps.at(-1);")
    assert last["kind"] == "image" and last["image"].endswith(".png"), last
    assert (CTX["storage"] / "noise" / last["image"]).is_file()


def test_broken_image_tolerated():
    page("guide=broken&mode=edit")
    time.sleep(1)
    assert js("return document.querySelectorAll('.step').length;") == 2
    assert js("return document.querySelectorAll('.imgfail').length;") == 2
    js("STATE.steps.splice(0, 1); renderSteps();")
    assert js("return document.querySelectorAll('.step').length;") == 1


_OPEN = ("openImageEditor(STATE.steps[0].id); await IED.ready;")
_PTR = ("const c = document.querySelector('.ied canvas'), r = c.getBoundingClientRect();"
        "const ev = (t, x, y) => c.dispatchEvent(new PointerEvent(t,"
        " {clientX: r.left + x, clientY: r.top + y, bubbles: true}));")
_STATE = ("return JSON.stringify([IED.step.image, IED.step.markers, IED.step.annotations,"
          " IED.step.redactions, IED.step.crop]);")


def test_editor_draws_box_and_undoes():
    page("guide=noise&mode=edit")
    js(_OPEN)
    n = js("return IED.step.annotations.length;")
    js(_PTR + "document.querySelector('.ied [data-tool=box]').click();"
       "ev('pointerdown', 20, 20); ev('pointermove', 120, 90); ev('pointerup', 120, 90);")
    assert js("return IED.step.annotations.length;") == n + 1
    a = js("return IED.step.annotations.at(-1);")
    assert a["type"] == "box" and a["w"] > 10 and a["h"] > 10, a
    js("IED.undo();")
    assert js("return IED.step.annotations.length;") == n


def test_editor_maps_coordinates():
    p = js("const c = document.querySelector('.ied canvas'), r = c.getBoundingClientRect();"
           "return IED.toImage(r.right - 1, r.bottom - 1);")
    assert 318 <= p["x"] <= 320 and 198 <= p["y"] <= 200, p  # noise image is 320x200


def test_undo_restores_replaced_image():
    before = js(_STATE)
    assert js(_png_js("r.png") + "return await IED.replaceImage(file);") is True
    assert js("return IED.step.markers.length + IED.step.annotations.length"
              " + IED.step.redactions.length;") == 0
    assert js("return IED.step.image;") != json.loads(before)[0]
    js("IED.undo(); await IED.ready;")
    assert js(_STATE) == before


def test_editor_gif_tools_disabled():
    js("closeImageEditor(); openImageEditor('a3'); await IED.ready;")
    assert js("return [...document.querySelectorAll('.ied [data-tool]')]"
              ".filter(b => b.dataset.tool !== 'select')"
              ".every(b => b.getAttribute('aria-disabled') === 'true');") is True
    js("closeImageEditor();")
    assert js("return document.querySelector('.ied') === null;") is True


def _corr(img, box) -> float:
    """Correlation of output pixels with the original noise inside box:
    0 = nothing of the original left, 1 = untouched."""
    x0, y0, w, h = box
    a, b = [], []
    for x in range(x0, x0 + w):
        for y in range(y0, y0 + h):
            a.extend(img.getpixel((x, y)))
            b.extend(NOISE.getpixel((x, y)))
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((v - ma) ** 2 for v in a)
    vb = sum((v - mb) ** 2 for v in b)
    if va < 1e-6:
        return 0.0
    return sum((p - ma) * (q - mb) for p, q in zip(a, b)) / (va * vb) ** 0.5


def test_blur_at_image_edges_hides_pixels():
    img = png(js("const g = await getJSON('/api/guide/edge');"
                 "return __b64(await renderStepPng(g.steps[0], 'edge'));"))
    assert abs(_corr(img, (0, 0, 100, 30))) < 0.1, _corr(img, (0, 0, 100, 30))
    assert abs(_corr(img, (300, 180, 20, 20))) < 0.1, _corr(img, (300, 180, 20, 20))


def test_blur_keeps_earlier_black():
    img = png(js("const g = await getJSON('/api/guide/edge');"
                 "return __b64(await renderStepPng(g.steps[1], 'edge'));"))
    assert _black(img, range(120, 180), range(80, 110))


def test_repeated_paste_from_caption_box():
    page("guide=noise&mode=edit")
    n = js("return STATE.steps.length;")
    js(_png_js("q.png") + "const box = document.querySelector('.stext'); box.focus();"
       "const dt = new DataTransfer(); dt.items.add(file);"
       "box.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));")
    got = js("for (let i = 0; i < 60 && STATE.steps.length === " + str(n) + "; i++)"
             "  await new Promise(r => setTimeout(r, 50));"
             "return STATE.steps.length;")
    assert got == n + 1, got


def test_gif_stays_locked_after_undo():
    js("openImageEditor('a3'); await IED.ready;")
    assert js(_png_js("u.png") + "return await IED.replaceImage(file);") is True
    js("document.querySelector('.ied [data-tool=blur]').click(); IED.undo(); await IED.ready;")
    js(_PTR + "ev('pointerdown', 2, 2); ev('pointermove', 30, 25); ev('pointerup', 30, 25);")
    assert js("return IED.step.redactions.length;") == 0
    assert js("return IED.tool;") == "select"
    js("closeImageEditor();")


def test_ring_takes_custom_colour():
    js(_OPEN + "IED.sel = {list: 'markers', item: IED.step.markers[0]}; iedOpts();")
    js("const i = document.querySelector('.ied-opts input[type=color]');"
       "i.value = '#123456'; i.dispatchEvent(new Event('change', {bubbles: true}));")
    assert js("return IED.step.markers[0].color;") == "#123456"
    js("closeImageEditor();")


def _draw_box():
    js(_PTR + "document.querySelector('.ied [data-tool=box]').click();"
       "ev('pointerdown', 20, 20); ev('pointermove', 120, 90); ev('pointerup', 120, 90);")


def test_ctrl_z_with_thai_layout():
    js(_OPEN)
    n = js("return IED.step.annotations.length;")
    _draw_box()
    assert js("return IED.step.annotations.length;") == n + 1
    # Ctrl+Z on a Thai layout: key is "ผ", the physical key is still KeyZ
    js("document.dispatchEvent(new KeyboardEvent('keydown',"
       " {key: 'ผ', code: 'KeyZ', ctrlKey: true, bubbles: true}));")
    assert js("return IED.step.annotations.length;") == n
    _draw_box()
    # after using the ring-size slider (focus on a range input) Ctrl+Z still works
    js("const r = document.createElement('input'); r.type = 'range';"
       "document.querySelector('.ied-opts').appendChild(r); r.focus();"
       "r.dispatchEvent(new KeyboardEvent('keydown',"
       " {key: 'z', code: 'KeyZ', ctrlKey: true, bubbles: true}));")
    assert js("return IED.step.annotations.length;") == n
    js("closeImageEditor();")


def test_resize_redaction_after_release():
    js(_OPEN)
    red = js("return IED.step.redactions[0];")  # black {20,20,60,40} on noise
    # select it, then drag its bottom-right corner handle further out
    js(_PTR + "document.querySelector('.ied [data-tool=select]').click();"
       "const k = r.width / c.width;"  # screen px per image px
       "ev('pointerdown', 50 * k, 40 * k); ev('pointerup', 50 * k, 40 * k);"
       "ev('pointerdown', 80 * k, 60 * k); ev('pointermove', 110 * k, 90 * k);"
       "ev('pointerup', 110 * k, 90 * k);")
    got = js("return IED.step.redactions[0];")
    assert (round(got["x"]), round(got["y"])) == (red["x"], red["y"]), got
    assert round(got["w"]) == 90 and round(got["h"]) == 70, got
    # the top-left handle moves that corner and keeps the opposite one
    js(_PTR + "const k = r.width / c.width;"
       "ev('pointerdown', 20 * k, 20 * k); ev('pointermove', 10 * k, 5 * k);"
       "ev('pointerup', 10 * k, 5 * k);")
    got = js("return IED.step.redactions[0];")
    assert (round(got["x"]), round(got["y"]), round(got["w"]), round(got["h"])) == (10, 5, 100, 85), got
    js("IED.undo(); IED.undo();")
    back = js("return IED.step.redactions[0];")
    assert (back["x"], back["y"], back["w"], back["h"]) == (red["x"], red["y"], red["w"], red["h"])
    js("closeImageEditor();")


def test_colour_picked_before_drawing():
    js(_OPEN)
    # pick red first, then place a ring: the ring is red
    js(_PTR + "document.querySelector('.ied [data-tool=marker]').click();"
       "document.querySelector('.ied-opts [data-c=\"#EF4444\"]').click();"
       "ev('pointerdown', 100, 100); ev('pointerup', 100, 100);")
    assert js("return IED.step.markers.at(-1).color;") == "#EF4444"
    # pick blue for the next ring: the one just placed stays red
    js(_PTR + "document.querySelector('.ied-opts [data-c=\"#3B82F6\"]').click();"
       "ev('pointerdown', 150, 120); ev('pointerup', 150, 120);")
    got = js("return IED.step.markers.slice(-2).map(m => m.color);")
    assert got == ["#EF4444", "#3B82F6"], got
    # the user's steps: green box, click elsewhere, purple, second box
    js(_PTR + "document.querySelector('.ied [data-tool=box]').click();"
       "document.querySelector('.ied-opts [data-c=\"#22C55E\"]').click();"
       "ev('pointerdown', 20, 20); ev('pointermove', 80, 60); ev('pointerup', 80, 60);"
       "ev('pointerdown', 250, 150); ev('pointerup', 250, 150);"
       "document.querySelector('.ied-opts [data-c=\"#A855F7\"]').click();"
       "ev('pointerdown', 120, 100); ev('pointermove', 200, 160); ev('pointerup', 200, 160);")
    got = js("return IED.step.annotations.slice(-2).map(a => a.type + a.color);")
    assert got == ["box#22C55E", "box#A855F7"], got
    js("closeImageEditor();")


def test_settings_page_redact():
    page("page=settings")
    got = js("await new Promise(r => setTimeout(r, 500));"
             "return [document.querySelector('#redon')?.checked,"
             " document.querySelectorAll('#setred [data-rule]:checked').length];")
    assert got == [True, 5], got
    js("const b = document.querySelector('#setred [data-rule=card]'); b.checked = false;"
       "b.dispatchEvent(new Event('change'));"
       "await new Promise(r => setTimeout(r, 300));")
    assert "card" not in js("return (await getJSON('/api/settings')).redact_rules;")


def test_redact_cover_and_note():
    page("guide=noise&mode=edit")
    assert js("redactCover([2, 5]); return [document.getElementById('redcover').textContent,"
              " document.getElementById('app').inert];") == ["กำลังซ่อนข้อมูล… 2/5", True]
    assert js("redactCover(null); return [document.getElementById('redcover'),"
              " document.getElementById('app').inert];") == [None, False]
    # the guide answers 409 twice (pass running), then comes with a note
    got = js("const f = window.fetch; let n = 0, covered = false;"
             "window.fetch = async (u, o) => {"
             "  if (String(u).startsWith('/api/guide/noise?')) {"
             "    if (n++ < 2) { covered = covered || !!document.getElementById('redcover');"
             "                   return new Response('redacting', {status: 409}); }"
             "    const j = await (await f(u, o)).json(); j.redact_note = 'NOTE-X';"
             "    return new Response(JSON.stringify(j)); }"
             "  return f(u, o); };"
             "await guidePage('noise', 'edit'); window.fetch = f;"
             "return [n, covered, STATE.redact_note === undefined,"
             " [...document.querySelectorAll('.toast')].some(t => t.textContent === 'NOTE-X')];")
    assert got == [3, True, True, True], got


_WAIT = ("const until = async f => { for (let i = 0; i < 150 && !f(); i++)"
         " await new Promise(r => setTimeout(r, 100)); };")
_TOASTS = "[...document.querySelectorAll('.toast')].map(t => t.textContent).join('|')"


def test_editor_redact_button():
    page("guide=pii&mode=edit")
    js("openImageEditor('p1'); await IED.ready;")
    js(_WAIT + "document.querySelector('.ied [data-act=redact]').click();"
       "await until(() => IED.step.redactions.length);")
    r = js("return IED.step.redactions;")
    assert len(r) == 1 and r[0]["x"] < 160 < r[0]["x"] + r[0]["w"], r
    # again: nothing new, says so, adds no undo step
    js(_WAIT + "document.querySelectorAll('.toast').forEach(t => t.remove());"
       "document.querySelector('.ied [data-act=redact]').click();"
       "await until(() => document.querySelector('.toast'));")
    assert "ไม่พบข้อมูลที่ต้องซ่อน" in js("return " + _TOASTS + ";")
    assert js("return IED.step.redactions.length;") == 1
    js("IED.undo();")
    assert js("return IED.step.redactions.length;") == 0
    js("closeImageEditor();")


def test_pasted_image_redacted():
    b64 = base64.b64encode(PII_PNG).decode()
    n = js("return STATE.steps.length;")
    js(_WAIT + f"const u = Uint8Array.from(atob('{b64}'), c => c.charCodeAt(0));"
       "const file = new File([u], 'pii.png', {type: 'image/png'});"
       "const dt = new DataTransfer(); dt.items.add(file);"
       "document.body.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true}));"
       f"await until(() => STATE.steps.length > {n} && STATE.steps.at(-1).redactions.length);")
    assert len(js("return STATE.steps.at(-1).redactions;")) == 1


TESTS = [test_bake_hides_pixels, test_export_contains_no_original,
         test_bake_redaction_across_crop, test_old_guide_exports_flattened,
         test_click_style_all_markers, test_text_paste_ignored,
         test_image_paste_adds_step, test_broken_image_tolerated,
         test_editor_draws_box_and_undoes, test_editor_maps_coordinates,
         test_undo_restores_replaced_image, test_editor_gif_tools_disabled,
         test_blur_at_image_edges_hides_pixels, test_blur_keeps_earlier_black,
         test_repeated_paste_from_caption_box, test_gif_stays_locked_after_undo,
         test_ring_takes_custom_colour, test_ctrl_z_with_thai_layout,
         test_resize_redaction_after_release, test_colour_picked_before_drawing,
         test_settings_page_redact, test_redact_cover_and_note,
         test_editor_redact_button, test_pasted_image_redacted]


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
