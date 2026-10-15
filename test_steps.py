"""Self-check for the pure step logic. Run: python test_steps.py"""
from recorder import StepBuilder, compose_click_text, control_noun


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
    assert compose_click_text("click", "Save", "ปุ่ม", "Notepad") \
        == 'คลิกปุ่ม "Save" ใน Notepad'
    assert compose_click_text("rightclick", "", "", "Notepad") \
        == "คลิกขวาใน Notepad"
    assert compose_click_text("doubleclick", "readme.txt", control_noun(50007),
                              "Explorer") == 'ดับเบิลคลิกรายการ "readme.txt" ใน Explorer'


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
    b.add_click("click", "OK", "ปุ่ม", "App")
    assert [s["kind"] for s in b.finish()] == ["type", "click"]


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
