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


def test_nearest_skips_empty():
    assert nearest([(0, 0, 0, 10), (90, 90, 110, 110), (10, 10, 30, 30)], (100, 100)) == (90, 90, 110, 110)
    assert nearest([(5, 5, 5, 5)], (0, 0)) is None


def test_resolve_element_on_negative_monitor():
    r = resolve(STEP, lambda e, t: W[1], lambda h, a, n, ty: [(-1890, 20, -1870, 40), (0, 0, 9, 9)], (0, 0))
    assert r["state"] == "element" and r["rect"] == (-1890, 20, -1870, 40) and r["shape"] == "box"


def test_resolve_approx_when_element_missing():
    r = resolve(STEP, lambda e, t: W[0], lambda *a: [], (0, 0))
    assert r["state"] == "approx" and r["shape"] == "circle" and r["rect"] == (118, 58, 162, 102)


def test_resolve_missing_window():
    r = resolve(STEP, lambda e, t: None, lambda *a: [], (0, 0))
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
