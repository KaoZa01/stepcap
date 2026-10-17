"""Self-check for Guide Me: target resolution and the step session.
Nothing here clicks or types on the desktop. Run: python test_guideme.py"""
from guideme import Session, button_ok, hit, nearest, pick_window, resolve

W = [{"hwnd": 1, "exe": "EXCEL.EXE", "title": "Book1", "rect": (100, 50, 900, 650)},
     {"hwnd": 2, "exe": "excel.exe", "title": "Report", "rect": (-1920, 0, -1000, 800)}]
T = {"exe": "excel.exe", "window": "Report", "dx": 40, "dy": 30, "name": "OK", "type": 50000}
STEP = {"kind": "click", "target": T, "markers": []}


def test_pick_window_prefers_title():
    assert pick_window(W, "excel.exe", "Report")["hwnd"] == 2
    assert pick_window(W, "excel.exe", "Other")["hwnd"] == 1
    assert pick_window(W, "word.exe", "Book1") is None


def test_pick_window_title_changed_uses_class():
    # Explorer recorded in "Documents", replayed in "Downloads": not the taskbar
    wins = [{"hwnd": 9, "exe": "explorer.exe", "title": "", "cls": "Shell_TrayWnd", "rect": (0, 1040, 1920, 1080)},
            {"hwnd": 5, "exe": "explorer.exe", "title": "Downloads", "cls": "CabinetWClass", "rect": (0, 0, 800, 600)}]
    assert pick_window(wins, "explorer.exe", "Documents", "CabinetWClass")["hwnd"] == 5
    assert pick_window(wins, "explorer.exe", "Documents")["hwnd"] == 9  # old target: no class known


def test_taskbar_is_a_window_to_search():
    # guides often start on the taskbar (Start, a pinned app): it must be findable
    from guideme import top_windows
    assert any(w["cls"] == "Shell_TrayWnd" and w["exe"].lower() == "explorer.exe"
               for w in top_windows())


def test_start_menu_is_a_window_to_search():
    # Start and Search live in a shell band EnumWindows leaves out; Start is
    # cloaked while closed, so look at the list before that filter
    import recorder
    from guideme import top_level_windows
    assert any(recorder.window_info(h)[1].lower() == "startmenuexperiencehost"
               for h in top_level_windows())


def test_panel_width_follows_scale():
    from guideme import panel_width
    assert panel_width(96) == 400 and panel_width(144) == 600 and panel_width(192) == 800
    from guideme import monitor_dpi
    assert monitor_dpi((0, 0)) >= 96  # the primary monitor's real DPI


def test_runner_failed_tick_clears_old_target():
    import time

    import guideme
    shown = []
    steps = [{"kind": "click", "markers": [{"x": 10, "y": 10, "size": 44}]},
             {"kind": "click", "markers": [{"x": 50, "y": 50, "size": 44}]}]
    r = guideme.Runner(steps, (0, 0), shown.append)
    end = time.time() + 3
    while not shown and time.time() < end:
        time.sleep(0.05)
    assert shown and shown[-1]["state"] == "approx"
    real = guideme.resolve
    guideme.resolve = lambda *a: (_ for _ in ()).throw(OSError("element gone"))
    try:
        r.next()
        end = time.time() + 3
        while r.state()["index"] != 1 and time.time() < end:
            time.sleep(0.05)
        time.sleep(0.2)
        assert r.state()["state"] == "none" and shown[-1]["state"] == "none", shown[-1]
    finally:
        guideme.resolve = real
        r.stop()


def test_nearest_skips_empty():
    assert nearest([(0, 0, 0, 10), (90, 90, 110, 110), (10, 10, 30, 30)], (100, 100)) == (90, 90, 110, 110)
    assert nearest([(5, 5, 5, 5)], (0, 0)) is None


def test_resolve_element_on_negative_monitor():
    r = resolve(STEP, lambda *a: W[1], lambda h, a, n, ty: [(-1890, 20, -1870, 40), (0, 0, 9, 9)], (0, 0))
    assert r["state"] == "element" and r["rect"] == (-1890, 20, -1870, 40) and r["shape"] == "box"


def test_resolve_approx_when_element_missing():
    r = resolve(STEP, lambda *a: W[0], lambda *a: [], (0, 0))
    assert r["state"] == "approx" and r["shape"] == "circle" and r["rect"] == (118, 58, 162, 102)


def test_resolve_approx_takes_the_button_at_that_spot():
    # element not found by name, but the button under the recorded spot is
    # known: outline (and hit-test) the whole button, not a marker-sized circle
    r = resolve(STEP, lambda *a: W[0], lambda *a: [], (0, 0),
                element_at=lambda pt, hwnd: (100, 60, 196, 144) if pt == (140, 80) and hwnd == 1 else None)
    assert r["state"] == "approx" and r["shape"] == "box" and r["rect"] == (100, 60, 196, 144)
    assert hit(r, 150, 135)  # the button's label, far from the recorded spot


def test_resolve_missing_window():
    r = resolve(STEP, lambda *a: None, lambda *a: [], (0, 0))
    assert r["state"] == "missing" and r["app"] == "excel"


def test_resolve_old_guide_uses_marker_and_origin():
    old = {"kind": "click", "markers": [{"x": 100, "y": 50, "size": 44}]}
    r = resolve(old, None, None, (1920, 0))
    assert r["state"] == "approx" and r["rect"] == (1998, 28, 2042, 72)


def test_resolve_none_cases():
    for s in ({"kind": "note"}, {"kind": "type"}, {"kind": "click", "markers": []}):
        assert resolve(s, None, None, (0, 0))["state"] == "none"


def test_hit_and_buttons():
    box = {"state": "element", "shape": "box", "rect": (10, 10, 20, 20)}
    assert hit(box, 25, 15) and not hit(box, 40, 15)
    circle = {"state": "approx", "shape": "circle", "rect": (0, 0, 44, 44)}
    assert hit(circle, 22, 22) and not hit(circle, 0, 0)
    assert not hit({"state": "none", "shape": None, "rect": None}, 0, 0)
    assert button_ok("rightclick", "right") and not button_ok("click", "right")
    assert button_ok("doubleclick", "left")


def test_session_flow():
    s = Session([{"kind": "click"}, {"kind": "note"}])
    box = {"state": "element", "shape": "box", "rect": (0, 0, 10, 10)}
    assert not s.on_click("left", 50, 50, box) and s.index == 0
    assert s.on_click("left", 5, 5, box) and s.index == 1
    s.back()
    assert s.index == 0
    s.go(2)
    assert s.done
    s.go(-3)
    assert s.index == 0 and not s.done


def test_uia_finds_own_button():
    # our own tk window, read through UI Automation; nothing is clicked
    import threading
    import time
    import tkinter as tk

    import recorder
    from guideme import UIAFind, top_windows
    recorder.set_dpi_aware()
    root = tk.Tk()
    root.title("gm-test")
    b = tk.Button(root, text="Press me")
    b.pack(padx=40, pady=40)
    root.update()
    # Tk leaves the native button's text empty for UIA; name it like Win32 apps do
    recorder.user32.SetWindowTextW(b.winfo_id(), "Press me")
    hwnd = recorder.find_main_window("gm-test")
    out = {}

    def work():
        try:
            f = UIAFind()
            out["rects"] = f.elements(hwnd, "", "Press me", 50000)
            r = out["rects"][0]
            c = ((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
            out["at"] = f.element_at(c, hwnd)
            out["foreign"] = f.element_at(c, recorder.user32.GetShellWindow())
            out["wins"] = top_windows(skip_own=False)
        except Exception as e:
            out["err"] = e

    th = threading.Thread(target=work)
    th.start()
    while th.is_alive():  # the window answers UIA from this thread
        root.update()
        time.sleep(0.01)
    bx, by, bw, bh = b.winfo_rootx(), b.winfo_rooty(), b.winfo_width(), b.winfo_height()
    root.destroy()
    assert "err" not in out, out.get("err")
    assert out["at"] == out["rects"][0], out  # the button under its own centre
    assert out["foreign"] is None             # the point is ours, not that pid's
    assert len(out["rects"]) == 1
    l, t, r, btm = out["rects"][0]
    assert bx <= (l + r) / 2 <= bx + bw and by <= (t + btm) / 2 <= by + bh
    me = [w for w in out["wins"] if w["hwnd"] == hwnd]
    assert me and me[0]["exe"].lower().startswith("python") and "\\" not in me[0]["exe"]
    assert all(w["hwnd"] != hwnd for w in top_windows())  # own windows skipped by default


def test_hook_forwards_clicks_not_on_own_windows():
    # the hook's decision only; no input is sent
    import tkinter as tk

    import recorder
    recorder.set_dpi_aware()
    r = recorder.Recorder.__new__(recorder.Recorder)
    r.recording = False
    got = []
    r.on_guide_click = lambda *a: got.append(a)
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.geometry("200x200+100+100")
    root.update()
    cx, cy = root.winfo_rootx() + 100, root.winfo_rooty() + 100
    r._guide_hook(recorder.WM_LBUTTONDOWN, cx, cy)       # StepCap's own window
    r._guide_hook(recorder.WM_LBUTTONUP, -30000, -30000)  # not a press
    r._guide_hook(recorder.WM_RBUTTONDOWN, -30000, -30000)
    r.recording = True
    r._guide_hook(recorder.WM_LBUTTONDOWN, -30000, -30000)  # recording wins
    root.destroy()
    assert got == [("right", -30000, -30000)], got


def test_overlay_highlight_box_and_hide():
    import threading

    import overlay
    import recorder
    recorder.set_dpi_aware()
    ov = overlay.Overlay()

    def ask(fn):  # run fn on the overlay's tk thread, return its value
        out, ev = {}, threading.Event()
        ov._q.put(lambda: (out.setdefault("v", fn()), ev.set()))
        assert ev.wait(3)
        return out["v"]

    ov.highlight({"state": "element", "shape": "box", "rect": (300, 200, 400, 240)})
    geo = ask(lambda: (ov._hl.winfo_rootx(), ov._hl.winfo_rooty(), ov._hl.winfo_width(),
                       ov._hl.winfo_height(), ov._hl.state()))
    assert geo == (293, 193, 114, 54, "normal"), geo
    ov.highlight({"state": "missing", "shape": None, "rect": None, "app": "x"})
    assert ask(lambda: ov._hl.state()) == "withdrawn"
    ask(lambda: ov._root.quit())


def test_panel_rect():
    from guideme import panel_rect
    assert panel_rect((0, 0, 1920, 1040), 360) == (1560, 0, 1920, 1040)
    assert panel_rect((-1280, 0, 0, 984), 360) == (-360, 0, 0, 984)
    assert panel_rect((0, 0, 1920, 1040), 540, "left") == (0, 0, 540, 1040)


def test_panel_moves_off_the_target():
    from guideme import panel_side
    work = (0, 0, 1920, 1040)
    assert panel_side(work, 360, (1800, 10, 1900, 40), "right") == "left"   # target under the panel
    assert panel_side(work, 360, (500, 10, 600, 40), "left") == "left"      # off both: stay put
    assert panel_side(work, 360, (500, 10, 600, 40), "right") == "right"
    assert panel_side(work, 360, (20, 10, 90, 40), "left") == "right"       # under it on the left
    assert panel_side(work, 360, (0, 0, 1920, 1040), "right") == "right"    # under both: stay put
    assert panel_side(work, 360, None, "left") == "left"


if __name__ == "__main__":
    import traceback
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
