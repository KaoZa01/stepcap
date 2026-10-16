"""End-to-end check: launches app.py on a temp storage and drives it over HTTP
plus read-only Win32 queries. The only message sent is WM_CLOSE to the test's
own StepCap window; no clicks or typing are synthesized. Windows only.
Run: python test_app.py"""
import base64
import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

import library
import recorder as R

HERE = Path(__file__).resolve().parent
U = R.user32
U.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                           wintypes.LPARAM]
U.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                          ctypes.c_wchar_p]
U.SendMessageW.restype = ctypes.c_ssize_t
U.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
U.EnumChildWindows.argtypes = [wintypes.HWND, R.WNDENUMPROC, wintypes.LPARAM]
WM_CLOSE, WM_SETTEXT, WM_GETTEXT, WM_COMMAND = 0x0010, 0x000C, 0x000D, 0x0111
WM_QUERYENDSESSION, SMTO_ABORTIFHUNG = 0x0011, 0x0002
U.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                  wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                  ctypes.POINTER(ctypes.c_size_t)]
U.SendMessageTimeoutW.restype = ctypes.c_ssize_t
OLD_ID = "20260101-090000"
OLD_GUIDE = {"id": OLD_ID, "title": "explorer - 1 ม.ค. 2569 09:00",
             "created": "2026-01-01T09:00:00",
             "steps": [{"id": "s1", "kind": "click",
                        "text": 'คลิกปุ่ม "Start" ใน explorer',
                        "image": None, "crop": None},
                       {"id": "s2", "kind": "note", "text": "หมายเหตุ"}]}

CTX: dict = {}


def wait(cond, secs, step=0.2):
    end = time.time() + secs
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    return None


def _req(path, body=None, token=True):
    sep = "&" if "?" in path else "?"
    url = f"http://127.0.0.1:{CTX['port']}{path}"
    if token:
        url += f"{sep}t={CTX['token']}"
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
    elif path.startswith("/api/") and token and CTX.get("post"):
        data = b"{}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data),
                                    timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code


def get(path, token=True):
    CTX["post"] = False
    return _req(path, token=token)


def post(path, body=None):
    CTX["post"] = True
    return _req(path, body if body is not None else b"{}")


def raw(path, token=True):
    sep = "&" if "?" in path else "?"
    url = f"http://127.0.0.1:{CTX['port']}{path}"
    if token:
        url += f"{sep}t={CTX['token']}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""


def find_win(pid):
    found = []

    def _cb(hwnd, _):
        if R.window_pid(hwnd) == pid and R.window_title(hwnd) == "StepCap":
            found.append(hwnd)
            return False
        return True

    U.EnumWindows(R.WNDENUMPROC(_cb), 0)
    return found[0] if found else None


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    U.GetClassNameW(hwnd, buf, 256)
    return buf.value


def save_dialog(pid):
    found = []

    def _cb(hwnd, _):
        if R.window_pid(hwnd) == pid and class_name(hwnd) == "#32770"                 and U.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    U.EnumWindows(R.WNDENUMPROC(_cb), 0)
    return found[0] if found else None


def all_children(hwnd):
    out = []

    def _cb(h, _):
        out.append(h)
        return True

    U.EnumChildWindows(hwnd, R.WNDENUMPROC(_cb), 0)
    return out


def child_edits(hwnd):
    out = []

    def _cb(h, _):
        if class_name(h) == "Edit" and U.IsWindowVisible(h):
            out.append(h)
        return True

    U.EnumChildWindows(hwnd, R.WNDENUMPROC(_cb), 0)
    return out


def edit_text(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(1024)
    U.SendMessageW(hwnd, WM_GETTEXT, 1024, ctypes.cast(buf, ctypes.c_wchar_p))
    return buf.value


def export_async(gid, body, route="export", base=None):
    out = {}
    base = base or f"/api/guide/{gid}"
    t = __import__("threading").Thread(
        target=lambda: out.setdefault("r", post(f"{base}/{route}", body)))
    t.start()
    return t, out


def _img(fmt: str) -> bytes:
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (8, 6), (0, 128, 255)).save(b, fmt)
    return b.getvalue()


def head_type(path):
    url = f"http://127.0.0.1:{CTX['port']}{path}?t={CTX['token']}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, None


def affinity(hwnd) -> int:
    v = wintypes.DWORD()
    U.GetWindowDisplayAffinity(hwnd, ctypes.byref(v))
    return v.value


def launch():
    return subprocess.Popen([sys.executable, "app.py"], cwd=HERE,
                            env={**__import__("os").environ,
                                 "STEPCAP_STORAGE": str(CTX["storage"])},
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def setup():
    st = Path(tempfile.mkdtemp(prefix="stepcap-e2e-"))
    CTX["storage"] = st
    (st / OLD_ID).mkdir()
    raw = json.dumps(OLD_GUIDE, ensure_ascii=False, indent=2).encode("utf-8")
    (st / OLD_ID / "guide.json").write_bytes(raw)
    CTX["old_bytes"] = raw
    CTX["proc"] = launch()
    run = wait(lambda: (st / "_run.json").exists() and json.loads(
        (st / "_run.json").read_text(encoding="utf-8")), 20)
    assert run, "_run.json never appeared (app did not start its server)"
    # the venv's python.exe is a launcher; the app runs in its child process
    CTX["port"], CTX["token"], CTX["pid"] = run["port"], run["token"], run["pid"]


def teardown():
    p = CTX.get("proc")
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       capture_output=True)
        p.wait(10)
    shutil.rmtree(CTX["storage"], ignore_errors=True)


def test_old_guide_untouched():
    g = get(f"/api/guide/{OLD_ID}")
    assert g["settings"] == library.DEFAULT_SETTINGS
    assert g["app"] == "explorer" and g["steps"][0]["markers"] == []
    assert (CTX["storage"] / OLD_ID / "guide.json").read_bytes() == \
        CTX["old_bytes"]


def test_window_is_ours():
    pid = CTX["pid"]
    win = wait(lambda: (h := find_win(pid)) and U.IsWindowVisible(h) and h, 15)
    assert win, "no visible StepCap window owned by the app process"
    CTX["win"] = win
    # The recorder skips a click when GA_ROOT of the window under the cursor
    # belongs to this pid. Check every descendant (WebView2's children live in
    # msedgewebview2 processes) instead of hit-testing, which depends on z-order.
    kids = wait(lambda: [h for h in all_children(win)
                         if R.window_pid(h) != pid], 15)
    assert kids, "no cross-process WebView2 child found under the window"
    for h in all_children(win):
        root = U.GetAncestor(h, R.GA_ROOT)
        assert root == win and R.window_pid(root) == pid, class_name(h)
    time.sleep(1.0)  # pywebview gates hide() on its "shown" event; let it settle


def test_close_hides_while_recording():
    win = CTX["win"]
    post("/api/start")
    assert get("/api/status")["recording"] is True
    assert affinity(win) == R.WDA_EXCLUDEFROMCAPTURE
    U.PostMessageW(win, WM_CLOSE, 0, 0)
    assert wait(lambda: not U.IsWindowVisible(win), 5), "X did not hide"
    time.sleep(0.5)
    assert CTX["proc"].poll() is None, "X quit the app"
    assert get("/api/status")["recording"] is True
    post("/api/stop")
    assert get("/api/status")["recording"] is False
    assert affinity(win) == 0


def test_second_instance_shows_window():
    win = CTX["win"]
    if U.IsWindowVisible(win):  # a stray real click during the test made a guide
        U.PostMessageW(win, WM_CLOSE, 0, 0)
        wait(lambda: not U.IsWindowVisible(win), 5)
    second = launch()
    assert second.wait(15) == 0
    assert wait(lambda: U.IsWindowVisible(win), 5), "window did not come back"


def test_library_routes():
    copy = post(f"/api/guide/{OLD_ID}/duplicate")["id"]
    ids = [s["id"] for s in get("/api/guides")]
    assert copy in ids and OLD_ID in ids
    post(f"/api/guide/{copy}/meta", {"bookmarked": True})
    assert [s["id"] for s in get("/api/guides?bookmarked=1")] == [copy]
    found = {s["id"] for s in get("/api/guides?q=Start")}
    assert {OLD_ID, copy} <= found
    post(f"/api/guide/{OLD_ID}/delete")
    assert OLD_ID not in [s["id"] for s in get("/api/guides")]
    assert OLD_ID in [t["id"] for t in get("/api/trash")]
    post(f"/api/trash/{OLD_ID}/restore")
    assert OLD_ID in [s["id"] for s in get("/api/guides")]
    post("/api/settings", {"view": "list"})
    assert get("/api/settings")["view"] == "list"
    assert get("/api/guide/_trash") == 404
    assert get("/api/guides", token=False) == 403


def test_redact_settings_route():
    post("/api/settings", {"redact_on": False})
    s = get("/api/settings")
    assert s["redact_on"] is False and "redact_error" in s, s
    assert post("/api/settings", {"redact_on": "yes"}) == 400
    assert post("/api/settings", {"redact_rules": ["email", "nope"]}) == 400
    post("/api/settings", {"redact_on": True, "redact_custom": ["acme"]})
    s = get("/api/settings")
    assert s["redact_on"] is True and s["redact_custom"] == ["acme"] and s["view"] == "list"


def test_redact_route():
    assert post(f"/api/guide/{OLD_ID}/redact", {"image": "nope.png", "force": True}) == 404
    assert post(f"/api/guide/{OLD_ID}/redact", {"image": "../x.png", "force": True}) == 404
    assert post(f"/api/guide/{OLD_ID}/redact", {"force": True}) == 400


def test_ui_served():
    code, html = raw("/")
    assert code == 200 and 'src="ui/shell.js"' in html
    code, js = raw("/ui/common.js", token=False)  # static source is ungated
    assert code == 200 and "function startStatusPoll" in js
    assert raw("/ui/..%2Fapp.py", token=False)[0] == 404
    assert raw("/ui/nope.js", token=False)[0] == 404
    assert raw("/", token=False)[0] == 403


def test_export_save_as():
    # cancel: nothing written, saved is null
    t, out = export_async(OLD_ID, b"<html>cancel</html>")
    dlg = wait(lambda: save_dialog(CTX["pid"]), 10)
    assert dlg, "no Save As dialog appeared"
    edits = child_edits(dlg)
    assert any(edit_text(e).endswith("09_00.html") for e in edits),         [edit_text(e) for e in edits]  # title-derived name, ":" made safe
    U.PostMessageW(dlg, WM_CLOSE, 0, 0)
    t.join(10)
    assert out["r"] == {"saved": None}
    # save: the page's bytes land at the chosen path
    target = CTX["storage"] / "export-test.html"
    t, out = export_async(OLD_ID, "<html>สวัสดี</html>".encode("utf-8"))
    dlg = wait(lambda: save_dialog(CTX["pid"]), 10)
    name_box = next(e for e in child_edits(dlg) if edit_text(e).endswith(".html"))
    U.SendMessageW(name_box, WM_SETTEXT, 0, str(target))
    U.PostMessageW(dlg, WM_COMMAND, 1, 0)  # IDOK
    t.join(10)
    assert Path(out["r"]["saved"]).resolve() == target.resolve(), out  # 8.3 vs long
    assert target.read_text(encoding="utf-8") == "<html>สวัสดี</html>"


def _export_to(route: str, body: bytes, target: Path, ext: str, base=None) -> dict:
    """POST an export, type `target` into the app's own Save As, return the reply."""
    t, out = export_async(OLD_ID, body, route=route, base=base)
    dlg = wait(lambda: save_dialog(CTX["pid"]), 30)
    assert dlg, "no Save As dialog appeared"
    box = next(e for e in child_edits(dlg) if edit_text(e).endswith(ext))
    U.SendMessageW(box, WM_SETTEXT, 0, str(target))
    U.PostMessageW(dlg, WM_COMMAND, 1, 0)  # IDOK
    t.join(60)
    return out["r"]


def test_export_pdf():
    png = base64.b64encode(_img("PNG")).decode()
    # empty <title> + an in-page link: neither may drag the temp file's path in
    html = (f'<!doctype html><html lang="th"><head><meta charset="utf-8"><title></title></head>'
            f'<body><a href="#s1">สารบัญ</a><h1 id="s1">คู่มือทดสอบ</h1>'
            f'<img src="data:image/png;base64,{png}"></body></html>').encode("utf-8")
    target = CTX["storage"] / "x.pdf"
    r = _export_to("export?format=pdf", html, target, ".pdf")
    assert Path(r["saved"]).resolve() == target.resolve(), r
    data = target.read_bytes()
    assert data.startswith(b"%PDF") and b"/Type /Page" in data
    low = data.lower()
    for needle in ("file:", CTX["storage"].name, "print-"):
        for enc in (needle.encode(), needle.encode("utf-16-be"),
                    needle.encode().hex().encode(), needle.encode("utf-16-be").hex().encode()):
            assert enc.lower() not in low, (needle, enc)
    tmp = CTX["storage"] / "_tmp"
    assert not list(tmp.glob("print-*")), list(tmp.glob("print-*"))


def test_export_md_and_docx():
    import zipfile
    from io import BytesIO
    png = _img("PNG")
    body = json.dumps({"images": [{"id": "s1", "ext": "png", "size": len(png)}]}).encode() \
        + b"\n" + png
    z = CTX["storage"] / "x.zip"
    r = _export_to("export?format=md", body, z, ".zip")
    assert Path(r["saved"]).resolve() == z.resolve(), r
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
        assert any(n.endswith(".md") for n in names) and f.read("images/step-01.png") == png, names
    d = CTX["storage"] / "x.docx"
    r = _export_to("export?format=docx", body, d, ".docx")
    assert Path(r["saved"]).resolve() == d.resolve(), r
    import docx
    assert len(docx.Document(str(d)).inline_shapes) == 1
    assert post(f"/api/guide/{OLD_ID}/export?format=nope", b"x") == 400


def test_page_routes():
    p = post("/api/pages", {"title": "เริ่มงาน"})
    pid = p["id"]
    assert pid in [x["id"] for x in get("/api/pages")]
    assert post(f"/api/page/{pid}/add", {"guide": OLD_ID}) == {"result": "added"}
    assert post(f"/api/page/{pid}/add", {"guide": OLD_ID}) == {"result": "exists"}
    assert post(f"/api/page/{pid}/add", {"guide": "nope"}) == 404
    page = get(f"/api/page/{pid}")
    assert page["guides"][OLD_ID]["title"] == OLD_GUIDE["title"], page
    doc = get(f"/api/page/{pid}/doc")
    assert [s["id"] for s in doc["steps"]][:2] == ["sec0", f"{OLD_ID}/s1"] and doc["missing"] == 0, doc
    assert post(f"/api/page/{pid}", {**page, "sections": [{"type": "guide", "guide": "../x"}]}) == 400
    assert post(f"/api/page/{pid}", {**page, "description": "ทดสอบ"}) == {}
    assert get(f"/api/page/{pid}")["description"] == "ทดสอบ"
    assert get("/api/page/..%2Fx") == 404
    assert post(f"/api/page/{pid}/delete") == {}
    assert get(f"/api/page/{pid}") == 404
    assert OLD_ID in [g["id"] for g in get("/api/guides")]  # the guide is untouched


def test_page_export_md():
    import zipfile
    pid = post("/api/pages", {"title": "รวม"})["id"]
    post(f"/api/page/{pid}/add", {"guide": OLD_ID})
    z = CTX["storage"] / "page.zip"
    r = _export_to("export?format=md", b'{"images": []}\n', z, ".zip", base=f"/api/page/{pid}")
    assert Path(r["saved"]).resolve() == z.resolve(), r
    with zipfile.ZipFile(z) as f:
        md = f.read("รวม.md").decode("utf-8")
    assert f"## {OLD_GUIDE['title']}" in md.replace("\\", ""), md


def test_upload_and_content_types():
    png, gif = _img("PNG"), _img("GIF")
    steps_before = get(f"/api/guide/{OLD_ID}")["steps"]
    name = post(f"/api/guide/{OLD_ID}/image", png)["image"]
    assert head_type(f"/img/{OLD_ID}/{name}") == (200, "image/png")
    gname = post(f"/api/guide/{OLD_ID}/image", gif)["image"]
    assert head_type(f"/img/{OLD_ID}/{gname}") == (200, "image/gif")
    assert post(f"/api/guide/{OLD_ID}/image", b"<html>") == 400
    assert get(f"/api/guide/{OLD_ID}")["steps"] == steps_before  # upload changes no step
    assert head_type(f"/img/{OLD_ID}/guide.json")[0] == 404      # not an image type


def test_download_save_as():
    assert post(f"/api/guide/{OLD_ID}/download?n=2", b"hello") == 400  # no dialog
    target = CTX["storage"] / "step2.png"
    body = _img("PNG")
    t, out = export_async(OLD_ID + "", body, route="download?n=2")
    dlg = wait(lambda: save_dialog(CTX["pid"]), 10)
    assert dlg, "no Save As dialog appeared"
    box = next(e for e in child_edits(dlg) if edit_text(e).endswith(".png"))
    assert edit_text(box).endswith("09_00 - ขั้นตอน 2.png"), edit_text(box)
    U.SendMessageW(box, WM_SETTEXT, 0, str(target))
    U.PostMessageW(dlg, WM_COMMAND, 1, 0)  # IDOK
    t.join(10)
    assert Path(out["r"]["saved"]).resolve() == target.resolve(), out
    assert target.read_bytes() == body


def test_shutdown_not_blocked():
    """Windows shutdown/sign-out must not be vetoed by X-hides-to-tray, and a
    running recording is saved first. Runs last: it may hide the window."""
    win = CTX["win"]
    post("/api/start")
    res = ctypes.c_size_t(0)
    ok = U.SendMessageTimeoutW(win, WM_QUERYENDSESSION, 0, 0, SMTO_ABORTIFHUNG,
                               5000, ctypes.byref(res))
    assert ok, "WM_QUERYENDSESSION timed out"
    assert res.value == 1, "StepCap vetoed the session end"
    assert get("/api/status")["recording"] is False, "recording not stopped first"
    assert CTX["proc"].poll() is None  # only a query: the app keeps running


def test_sample_route_and_settings():
    titles = lambda: [g["title"] for g in get("/api/guides")].count(library.SAMPLE_TITLE)
    if (HERE / "samples" / "getting-started" / "guide.json").is_file():
        n = titles()
        assert n == 1, n  # copied once at first launch
        assert get(f"/api/guide/{post('/api/sample')['id']}")["title"] == library.SAMPLE_TITLE
        assert titles() == n + 1
    else:
        assert post("/api/sample") == 500
    post("/api/settings", {"tours_seen": ["home"]})
    assert get("/api/settings")["tours_seen"] == ["home"]
    assert post("/api/settings", {"tours_seen": ["bogus"]}) == 400
    assert post("/api/settings", {"sample_added": False}) == 400


def test_lang_route():
    assert post("/api/settings", {"lang": "fr"}) == 400
    try:
        post("/api/settings", {"lang": "en"})
        assert get("/api/settings")["lang"] == "en"
        code, html = raw("/")
        assert code == 200 and '<html lang="en">' in html and 'const LANG="en"' in html, html[:200]
    finally:
        post("/api/settings", {"lang": "th"})
    assert '<html lang="th">' in raw("/")[1]


TESTS = [test_old_guide_untouched, test_window_is_ours,
         test_close_hides_while_recording, test_second_instance_shows_window,
         test_library_routes, test_sample_route_and_settings, test_redact_settings_route, test_redact_route, test_lang_route,
         test_ui_served, test_export_save_as,
         test_upload_and_content_types, test_download_save_as, test_export_pdf,
         test_export_md_and_docx, test_page_routes, test_page_export_md,
         test_shutdown_not_blocked]

if __name__ == "__main__":
    import traceback
    sys.stdout.reconfigure(encoding="utf-8")
    failed = 0
    try:
        setup()
        for fn in TESTS:
            try:
                fn()
                print(f"ok   {fn.__name__}")
            except Exception:
                failed += 1
                print(f"FAIL {fn.__name__}")
                traceback.print_exc()
    except Exception:
        failed = len(TESTS)
        print("FAIL setup")
        traceback.print_exc()
    finally:
        teardown()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    raise SystemExit(1 if failed else 0)
