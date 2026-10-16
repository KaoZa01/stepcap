"""Rebuilds samples/getting-started/: the sample guide StepCap copies in on
first launch. Its pictures are StepCap's own screens with made-up guides.

Run: .venv/Scripts/python.exe samples/make_getting_started.py

Launches StepCap on a temp folder and opens a window of its own on it; the
web screens come from WebView2's CapturePreviewAsync (only the page, never
the desktop) and the recording panel from PrintWindow (only that window).
The panel shows in the bottom-right corner for about a second. No clicks
or keys are sent anywhere. Look at every picture before committing them.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "getting-started"
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import library  # noqa: E402

FONT = "LeelawUI.ttf"
ORANGE = "#FB923C"


# ------------------------------------------------------------------ fake library
def _screen(title: str, lines: list[str]) -> bytes:
    """A plain made-up app screen: a title bar and a form."""
    img = Image.new("RGB", (960, 540), "#f3f4f6")
    d = ImageDraw.Draw(img)
    big, small = ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT, 20)
    d.rectangle([0, 0, 960, 56], fill="#1e3a8a")
    d.text((24, 12), title, font=big, fill="white")
    for i, text in enumerate(lines):
        y = 100 + i * 80
        d.text((60, y), text, font=small, fill="#111827")
        d.rounded_rectangle([300, y - 6, 860, y + 34], 6, fill="white", outline="#9ca3af")
    d.rounded_rectangle([700, 440, 860, 490], 8, fill="#2563eb")
    d.text((745, 450), "บันทึก", font=small, fill="white")
    b = BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


FAKE = [
    ("ระบบลางาน", "16 ต.ค. 2569 09:12", "2026-10-16T09:12:00",
     ["คลิก ปุ่ม 'ขอลา' ใน ระบบลางาน", "เลือก 'ลาพักร้อน' ในรายการ ประเภทการลา", "คลิก ปุ่ม 'ส่งคำขอ'"],
     ["ประเภทการลา", "วันที่เริ่ม", "วันที่สิ้นสุด", "เหตุผล"]),
    ("ตั้งค่าอีเมล Outlook", "15 ต.ค. 2569 14:30", "2026-10-15T14:30:00",
     ["คลิก เมนู 'ไฟล์'", "คลิก ปุ่ม 'เพิ่มบัญชี'", "พิมพ์ 'สมชาย@ตัวอย่าง.co.th' ใน ช่อง อีเมล"],
     ["อีเมล", "ชื่อที่แสดง", "เซิร์ฟเวอร์"]),
    ("เบิกค่าเดินทาง", "14 ต.ค. 2569 10:05", "2026-10-14T10:05:00",
     ["คลิก ปุ่ม 'สร้างใบเบิก'", "พิมพ์ '350' ใน ช่อง จำนวนเงิน", "คลิก ปุ่ม 'แนบใบเสร็จ'"],
     ["รายการ", "จำนวนเงิน", "แนบใบเสร็จ"]),
]


def seed(st: Path) -> str:
    """Three made-up guides; returns the id of the leave-system one."""
    for i, (app, when, iso, steps, fields) in enumerate(FAKE):
        gid = f"2026101{6 - i}-0900{i}0"
        (st / gid).mkdir()
        shot = _screen(app, fields)
        out = []
        for n, text in enumerate(steps, 1):
            (st / gid / f"s{n}.png").write_bytes(shot)
            out.append({"id": f"s{n}", "kind": "type" if text.startswith("พิมพ์") else "click",
                        "text": text, "image": f"s{n}.png", "crop": None,
                        "markers": [{"x": 580, "y": 100 + (n - 1) * 80 + 14, "size": 44,
                                     "color": ORANGE, "shape": "circle"}],
                        "annotations": [], "redactions": []})
        (st / gid / "guide.json").write_text(json.dumps(
            {"id": gid, "title": f"{app} - {when}", "created": iso, "updated": iso, "app": app,
             "settings": dict(library.DEFAULT_SETTINGS), "steps": out}, ensure_ascii=False),
            encoding="utf-8")
    # tours seen and no sample: the screens show the plain app
    (st / "settings.json").write_text(json.dumps(
        {"tours_seen": list(library.TOURS), "sample_added": True}), encoding="utf-8")
    return "20261016-090000"


# ------------------------------------------------------------------ capture
def shoot(win) -> Image.Image:
    """The page as the user sees it, in CSS pixels (same on any display scale)."""
    from System import Action
    from System.IO import MemoryStream
    from System.Threading.Tasks import Task
    from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat as Fmt
    done, res = threading.Event(), {}

    def go():
        ms = MemoryStream()
        core = win.native.browser.webview.CoreWebView2

        def finished(t):
            res["png"] = bytes(ms.ToArray())
            done.set()
        core.CapturePreviewAsync(Fmt.Png, ms).ContinueWith(Action[Task](finished))
    win.native.Invoke(Action(go))
    assert done.wait(20), "capture timed out"
    img = Image.open(BytesIO(res["png"])).convert("RGB")
    w, h = win.evaluate_js("[innerWidth, innerHeight]")
    return img.resize((w, h), Image.LANCZOS) if img.size != (w, h) else img


def center(win, sel: str) -> dict:
    x, y = win.evaluate_js(f"(r => [r.left + r.width / 2, r.top + r.height / 2])"
                           f"(document.querySelector({json.dumps(sel)}).getBoundingClientRect())")
    return {"x": round(x), "y": round(y), "size": 44, "color": ORANGE, "shape": "circle"}


def wait_js(win, cond: str, secs=20):
    end = time.time() + secs
    while time.time() < end:
        if win.evaluate_js(f"!!({cond})"):
            return
        time.sleep(0.2)
    raise TimeoutError(cond)


def open_page(base: str, query: str):
    w = webview.create_window("sample-shots", base + "&" + query, width=1280, height=820, x=20, y=20)
    w.events.loaded.wait(20)
    time.sleep(2)
    return w


def panel_shots() -> tuple[Image.Image, dict]:
    """The real recording panel with made-up steps, and the stop button's centre."""
    import ctypes
    from ctypes import wintypes

    import overlay
    ov = overlay.Overlay()
    ov._ready.wait(10)
    state = {"recording": True, "paused": False, "pending": None,
             "steps": [{"text": t} for t in FAKE[0][3]]}
    work = (0, 0, 1920, 1040)
    ov.show_panel(work, lambda: state, lambda: None, lambda: None)
    time.sleep(1.0)
    got, ready = {}, threading.Event()

    def info():  # on the tk thread
        win = ov._panel
        got["hwnd"] = int(win.wm_frame(), 16)
        stop = next(w for w in win.winfo_children()[-1].winfo_children() if w.cget("text") == "หยุดบันทึก")
        got["stop"] = (stop.winfo_rootx() - win.winfo_rootx() + stop.winfo_width() // 2,
                       stop.winfo_rooty() - win.winfo_rooty() + stop.winfo_height() // 2)
        got["size"] = (win.winfo_width(), win.winfo_height())
        # the panel keeps itself out of screenshots (so recordings never show
        # it); this one picture of it needs that off
        ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(got["hwnd"]), 0)
        ready.set()
    ov._q.put(info)
    assert ready.wait(10)
    time.sleep(0.5)
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    w, h = got["size"]
    hdc = u.GetDC(None)
    mdc, bmp = g.CreateCompatibleDC(hdc), g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(wintypes.HWND(got["hwnd"]), mdc, 2)  # PW_RENDERFULLCONTENT: this window only

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32), ("rest", ctypes.c_uint32 * 6)]
    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    g.DeleteObject(bmp); g.DeleteDC(mdc); u.ReleaseDC(None, hdc)
    ov.hide_panel()
    img = Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    return img, {"x": got["stop"][0], "y": got["stop"][1], "size": 44, "color": ORANGE, "shape": "circle"}


# ------------------------------------------------------------------ the guide
STEPS = [  # spec 3.1, in order: (kind, text, picture or None)
    ("note", "คู่มือนี้ทำด้วย StepCap เอง กด แก้ไข เพื่อลองแก้ข้อความ แก้ภาพ หรือส่งออกได้เลย "
             "ไม่ใช้แล้วลบทิ้งได้จากเมนู … ของการ์ด", None),
    ("click", "คลิก \"+ บันทึกใหม่\" ที่มุมขวาบน", "home"),
    ("click", "เลือกจอที่จะบันทึก แล้วคลิก \"เริ่มบันทึก\"", "recmenu"),
    ("image", "ทำงานในโปรแกรมที่จะสอนตามปกติ หน้าต่าง StepCap จะย่อลง ทุกคลิกและการพิมพ์จะขึ้นในแผงมุมขวาล่าง "
              "กด \"พัก\" หรือ Ctrl+Alt+P ถ้าจะทำอะไรที่ไม่อยากให้บันทึก", "panel"),
    ("click", "คลิก \"หยุดบันทึก\" ที่แผง (หรือกด Ctrl+Alt+R) คู่มือจะเปิดให้แก้ไขทันที", "panel_stop"),
    ("image", "แก้ข้อความของแต่ละขั้นได้ในช่อง ลบขั้นที่ไม่ต้องการด้วยไอคอนถังขยะ และเรียงลำดับด้วยปุ่มขึ้น/ลง", "edit"),
    ("click", "คลิก \"แก้ไขภาพ\" เพื่อใส่ลูกศร กรอบ ข้อความ เบลอข้อมูล หรือครอปภาพ", "edit_ed"),
    ("click", "คลิก \"ส่งออก\" แล้วเลือก Word, PDF, HTML หรือ Markdown แล้วเลือกที่บันทึกไฟล์", "export"),
    ("note", "⚠ ก่อนส่งให้คนอื่น: ตรวจภาพทุกภาพอีกครั้ง ระบบเบลอข้อมูลอัตโนมัติอ่านได้เฉพาะตัวอักษรอังกฤษและตัวเลข "
             "และส่งเฉพาะไฟล์ที่ส่งออก อย่าส่งทั้งโฟลเดอร์ StepCap เพราะมีภาพต้นฉบับก่อนเบลอ", None),
    ("note", "รู้ไว้ว่ามี: เมนู Page ใช้รวมหลายคู่มือเป็นเอกสารเดียว · ถังขยะกู้คู่มือที่ลบได้ · "
             "ตั้งค่ามีที่เก็บไฟล์ ปุ่มลัด และปุ่มแสดงคำแนะนำอีกครั้ง", None),
]


def app_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(251, 146, 60, 255))
    d.ellipse([16, 16, 48, 48], outline=(255, 255, 255, 255), width=7)
    return img


def capture(base: str, leave_id: str) -> dict:
    """name -> (picture, marker or None)"""
    shots = {}
    w = open_page(base, "page=home")
    wait_js(w, "document.querySelector('.card')")
    w.evaluate_js("document.activeElement.blur(); 1")
    shots["home"] = (shoot(w), center(w, "#recbtn"))
    w.evaluate_js("document.getElementById('recbtn').click(); 1")
    wait_js(w, "!document.getElementById('recmenu').hidden && document.querySelector('#recmenu .mon')")
    # the real monitor list would show this machine's screens
    w.evaluate_js("document.querySelectorAll('#recmenu .mon span:not(.ck)').forEach((s, i) =>"
                  " s.textContent = i ? 'จอ 2 · 1920×1080' : 'จอ 1 · 1920×1080 · จอหลัก');"
                  "[...document.querySelectorAll('#recmenu .mon')].slice(2).forEach(m => m.remove());"
                  "document.activeElement.blur(); 1")
    shots["recmenu"] = (shoot(w), center(w, "#startrec"))
    w.destroy()
    w = open_page(base, f"guide={leave_id}&mode=edit")
    wait_js(w, "document.querySelector('.eprev canvas') && document.querySelector('.eprev canvas').width > 1")
    time.sleep(0.5)
    w.evaluate_js("document.activeElement.blur(); 1")
    shots["edit"] = (shoot(w), None)
    shots["edit_ed"] = (shots["edit"][0], center(w, ".step .ed"))
    w.evaluate_js("document.getElementById('exp').click(); 1")
    wait_js(w, "document.querySelector('.menu-pop')")
    w.evaluate_js("document.activeElement.blur(); 1")
    shots["export"] = (shoot(w), center(w, "#exp"))
    w.destroy()
    return shots


def main(holder, base, leave_id, result):
    try:
        shots = capture(base, leave_id)
        panel, stop = panel_shots()
        shots["panel"], shots["panel_stop"] = (panel, None), (panel, stop)
        result["shots"] = shots
    except Exception:
        import traceback
        result["error"] = traceback.format_exc()
    finally:
        holder.destroy()


def write(shots: dict):
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    app_icon().save(OUT / "app_icon.png")
    steps, n = [], 0
    for i, (kind, text, shot) in enumerate(STEPS, 1):
        s = {"id": f"s{i:02d}", "kind": kind, "text": text, "image": None, "crop": None,
             "markers": [], "annotations": [], "redactions": []}
        if shot:
            n += 1
            img, marker = shots[shot]
            name = f"step-{n:02d}.png"
            img.save(OUT / name, optimize=True)
            s["image"] = name
            if marker:
                s["markers"] = [marker]
        steps.append(s)
    (OUT / "guide.json").write_text(json.dumps(
        {"id": "getting-started", "title": library.SAMPLE_TITLES["th"], "created": "2026-10-16T09:00:00",
         "updated": "2026-10-16T09:00:00", "bookmarked": False, "app": "StepCap",
         "app_icon": "app_icon.png", "settings": dict(library.DEFAULT_SETTINGS), "steps": steps},
        ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    st = Path(tempfile.mkdtemp(prefix="stepcap-sample-"))
    proc = None
    try:
        leave = seed(st)
        proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT,
                                env={**os.environ, "STEPCAP_STORAGE": str(st)},
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.time() + 20
        while time.time() < end and not (st / "_run.json").exists():
            time.sleep(0.2)
        run = json.loads((st / "_run.json").read_text(encoding="utf-8"))
        base = f"http://127.0.0.1:{run['port']}/?t={run['token']}"
        result = {}
        holder = webview.create_window("holder", html="<p>.</p>", hidden=True)
        webview.start(main, (holder, base, leave, result), private_mode=True)
        if "error" in result:
            raise SystemExit(result["error"])
        write(result["shots"])
        print("wrote", OUT)
    finally:
        if proc and proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        shutil.rmtree(st, ignore_errors=True)
