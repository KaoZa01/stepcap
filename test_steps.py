"""Self-check for the pure step logic. Run: python test_steps.py"""
import time

import i18n
from recorder import (Recorder, StepBuilder, clickable_ancestor, compose_click_text,
                      control_noun, monitor_index, title_stamp)


def test_clickable_ancestor_walks_up():
    chain = [{"name": "Save", "type": 50020, "aid": ""},      # Text inside
             {"name": "Save", "type": 50000, "aid": ""},      # Button
             {"name": "Toolbar", "type": 50021, "aid": "tb"}]
    assert clickable_ancestor(chain)["type"] == 50000


def test_clickable_ancestor_aid_counts():
    chain = [{"name": "", "type": 50020, "aid": ""}, {"name": "x", "type": 50033, "aid": "pane1"}]
    assert clickable_ancestor(chain)["aid"] == "pane1"


def test_clickable_ancestor_falls_back_to_hit():
    chain = [{"name": "a", "type": 50020, "aid": ""}, {"name": "b", "type": 50033, "aid": ""}]
    assert clickable_ancestor(chain)["name"] == "a"


def test_click_step_keeps_target():
    b = StepBuilder()
    t = {"exe": "notepad.exe", "window": "Untitled", "dx": 5, "dy": 6, "name": "Save", "type": 50000}
    s = b.add_click("click", "Save", 50000, "notepad", target=t)
    assert s["target"] == t
    assert "target" not in StepBuilder().add_click("click", "x", 50000, "a")


def test_steps_record_what_to_press():
    # Guide Me moves on when the person types / presses what was recorded
    b = StepBuilder()
    for c in "hi":
        b.add_key(c, None, "Name", False)
    b.add_key(None, "Enter", "Name", False)
    b.add_key(None, "Tab", "", False)          # Tab on its own
    b.add_key(None, "ลูกศรขวา", "", False)     # i18n-ok: an arrow on its own
    b.add_shortcut(["Ctrl"], "S")
    for c in "pw":
        b.add_key(c, None, "Password", True)
    b.add_key(None, "Tab", "Password", True)
    s = b.finish()
    assert [x.get("expect") for x in s] == [
        {"typed": "hi", "ending": "Enter"}, {"key": "Tab"}, {"key": "ลูกศรขวา"},  # i18n-ok
        {"keys": "Ctrl + S"}, {"ending": "Tab"}]


def test_masked_typing_keeps_no_typed_value():
    b = StepBuilder(mask=lambda t: "•••" if "@" in t else t)
    for c in "a@b.co":
        b.add_key(c, None, "Email", False)
    s = b.finish()[0]
    assert "typed" not in s.get("expect", {}) and "a@b.co" not in str(s)


def test_commit_click_records_window_class():
    r = Recorder.__new__(Recorder)
    r._builder = StepBuilder()
    r.monitors = [{"left": 0, "top": 0}]
    r.selected = 0
    r._last_click = None
    pend = (110, 220, "Save", 50000, "Docs", "explorer", None, r"C:\Windows\explorer.exe",
            {"name": "Save", "type": 50000, "aid": ""}, (100, 200, 900, 800), "CabinetWClass")
    r._commit_click("click", pend, 1.0)
    t = r._builder.steps[0]["target"]
    assert t == {"exe": "explorer.exe", "window": "Docs", "cls": "CabinetWClass", "dx": 10,
                 "dy": 20, "name": "Save", "type": 50000}, t


def test_write_guide_keeps_target_not_app():
    import json, shutil, tempfile
    from pathlib import Path
    st = Path(tempfile.mkdtemp(prefix="stepcap-steps-"))
    try:
        r = Recorder.__new__(Recorder)
        r.storage = st
        b = StepBuilder()
        b.add_click("click", "Save", 50000, "StepCap", exe=r"C:\Users\x\a.exe",
                    target={"exe": "a.exe", "window": "W", "dx": 1, "dy": 2,
                            "name": "Save", "type": 50000})
        g = r._write_guide(b.finish())
        s = json.loads((st / g["id"] / "guide.json").read_text(encoding="utf-8"))["steps"][0]
        assert s["target"]["exe"] == "a.exe" and "\\" not in json.dumps(s["target"])
        assert "app" not in s and "exe" not in s
    finally:
        shutil.rmtree(st, ignore_errors=True)


def _typed(b):
    return [s["text"] for s in b.finish()]


def test_typing_and_enter():
    b = StepBuilder()
    for ch in "สมชาย":
        b.add_key(ch, None, "ชื่อ", False)
    b.add_key(None, "Enter", "ชื่อ", False)
    assert _typed(b) == ['พิมพ์ "สมชาย" ในช่อง "ชื่อ" แล้วกด Enter']


def test_backspace_shows_final():
    b = StepBuilder()
    for ch in "สมชา":
        b.add_key(ch, None, "", False)
    b.add_key(None, "Backspace", "", False)  # delete า
    b.add_key("ด", None, "", False)
    assert _typed(b) == ['พิมพ์ "สมชด"']


def test_password_hides_text():
    b = StepBuilder()
    for ch in "secret123":
        b.add_key(ch, None, "Password", True)
    out = b.finish()
    assert out[0]["kind"] == "password"
    assert out[0]["text"] == 'พิมพ์รหัสผ่านในช่อง "Password"'
    assert "secret" not in out[0]["text"]


def test_mask_typed_text():
    b = StepBuilder(mask=lambda t: t.replace("me@x.co", "•••"))
    for ch in "me@x.co":
        b.add_key(ch, None, "", False)
    assert b.pending_text() == 'พิมพ์ "•••"'  # live list is masked too
    b.add_key(None, "Enter", "", False)
    assert _typed(b) == ['พิมพ์ "•••" แล้วกด Enter']


def test_mask_field_name_too():
    # some apps name an edit box after its current value
    b = StepBuilder(mask=lambda t: t.replace("me@x.co", "•••"))
    b.add_key("a", None, "me@x.co", False)
    assert _typed(b) == ['พิมพ์ "a" ในช่อง "•••"']


def test_field_change_splits():
    b = StepBuilder()
    b.add_key("a", None, "ชื่อ", False)
    b.add_key("b", None, "อีเมล", False)
    assert _typed(b) == ['พิมพ์ "a" ในช่อง "ชื่อ"', 'พิมพ์ "b" ในช่อง "อีเมล"']


def test_shortcut():
    b = StepBuilder()
    b.add_shortcut(["Ctrl"], "S")
    assert _typed(b) == ["กด Ctrl + S"]


def test_shortcut_flushes_typing():
    b = StepBuilder()
    b.add_key("h", None, "", False)
    b.add_key("i", None, "", False)
    b.add_shortcut(["Ctrl"], "S")
    assert _typed(b) == ['พิมพ์ "hi"', "กด Ctrl + S"]


def test_click_text():
    assert compose_click_text("click", "Save", 50000, "Notepad") \
        == 'คลิกปุ่ม "Save" ใน Notepad'
    assert compose_click_text("rightclick", "", 0, "Notepad") \
        == "คลิกขวาใน Notepad"
    assert compose_click_text("doubleclick", "readme.txt", 50007,
                              "Explorer") == 'ดับเบิลคลิกรายการ "readme.txt" ใน Explorer'
    assert control_noun(50007) == "รายการ"


def test_english_step_text():
    with i18n.using("en"):
        assert compose_click_text("click", "Save", 50000, "Excel") == 'Click the "Save" button in Excel'
        assert compose_click_text("rightclick", "Report.xlsx", 50007, "File Explorer") \
            == 'Right-click the "Report.xlsx" item in File Explorer'
        assert compose_click_text("doubleclick", "", 0, "Excel") == "Double-click in Excel"
        assert compose_click_text("click", "OK", 0, "") == 'Click "OK"'
        b = StepBuilder()
        for ch in "hello":
            b.add_key(ch, None, "Name", False)
        b.add_key(None, "Enter", "Name", False)
        b.add_key("x", None, "Password", True)
        b.add_key(None, "Tab", "Password", True)
        b.add_key("y", None, "", True)
        b.add_shortcut(["Ctrl"], "C")
        b.add_key(None, "ลูกศรซ้าย", "", False)  # i18n-ok: VK_SPECIAL's arrow name
        b.add_shortcut(["Ctrl"], "ลูกศรขวา")  # i18n-ok
        assert _typed(b) == ['Type "hello" in the "Name" field then press Enter',
                             'Type a password in the "Password" field then press Tab',
                             "Type a password", "Press Ctrl + C", "Press Left arrow",
                             "Press Ctrl + Right arrow"], _typed(b)


def test_title_stamp():
    t = time.mktime((2026, 10, 16, 10, 5, 0, 0, 0, -1))
    assert title_stamp(t) == "16 ต.ค. 2569 10:05"
    with i18n.using("en"):
        assert title_stamp(t) == "16 Oct 2026 10:05"


def test_pending_text_for_live_list():
    b = StepBuilder()
    assert b.pending_text() is None
    b.add_key("ก", None, "ชื่อ", False)
    assert b.pending_text() == 'พิมพ์ "ก" ในช่อง "ชื่อ"'
    b.add_key(None, "Enter", "ชื่อ", False)
    assert b.pending_text() is None
    b.add_key("x", None, "Password", True)
    assert b.pending_text() == 'พิมพ์รหัสผ่านในช่อง "Password"'


def test_click_flushes_typing():
    b = StepBuilder()
    b.add_key("x", None, "", False)
    b.add_click("click", "OK", 50000, "App")
    assert [s["kind"] for s in b.finish()] == ["type", "click"]


def test_monitor_index_fallback():
    mons = [{"index": 0, "name": r"\\.\DISPLAY1", "primary": False},
            {"index": 1, "name": r"\\.\DISPLAY2", "primary": True}]
    assert monitor_index(mons, r"\\.\DISPLAY1") == 0
    assert monitor_index(mons, r"\\.\DISPLAY9") == 1   # unplugged -> primary
    assert monitor_index(mons, None) == 1
    assert monitor_index([{"index": 0, "name": "x", "primary": False}], None) == 0


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
