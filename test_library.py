"""Self-check for library.py (guides on disk). Run: python test_library.py"""
import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from library import (DEFAULT_APP_SETTINGS, DEFAULT_SETTINGS, MAX_IMAGE,
                     add_image, duplicate_guide, empty_trash, image_kind,
                     list_guides, list_trash, load_settings, new_id, normalize,
                     purge_guide, rel_time, restore_guide, save_guide,
                     save_settings, step_count, trash_guide, update_meta)


def _seed(storage: Path, gid: str, title="T", created="2026-10-01T10:00:00",
          steps=None, **fields) -> Path:
    folder = storage / gid
    folder.mkdir(parents=True)
    g = {"id": gid, "title": title, "created": created,
         "steps": steps if steps is not None else
         [{"id": "s1", "kind": "click", "text": "คลิก"}], **fields}
    (folder / "guide.json").write_text(json.dumps(g, ensure_ascii=False),
                                       encoding="utf-8")
    return folder


def _load(storage: Path, *parts) -> dict:
    return json.loads(storage.joinpath(*parts, "guide.json")
                      .read_text(encoding="utf-8"))


def _fake_recycle(calls):
    def recycle(path):
        calls.append(path)
        shutil.rmtree(path)
    return recycle


def test_rel_time():
    now = datetime(2026, 10, 15, 12, 0, 0)
    assert rel_time("2026-10-15T11:59:30", now) == "เมื่อสักครู่"
    assert rel_time("2026-10-15T11:55:00", now) == "5 นาทีที่แล้ว"
    assert rel_time("2026-10-15T09:00:00", now) == "3 ชั่วโมงที่แล้ว"
    assert rel_time("2026-10-13T12:00:00", now) == "2 วันที่แล้ว"
    assert rel_time("2026-05-15T12:00:00", now) == "5 เดือนที่แล้ว"
    assert rel_time("2024-10-15T12:00:00", now) == "2 ปีที่แล้ว"
    assert rel_time("2026-10-15T12:00:05", now) == "เมื่อสักครู่"  # clock skew
    assert rel_time("", now) == "" and rel_time("garbage", now) == ""


def test_normalize_minimal_old_guide():
    old = {"id": "20261015-153012", "title": "explorer - 15 ต.ค. 2569 15:30",
           "steps": [{"id": "a", "kind": "click", "text": "x"},
                     {"id": "b", "kind": "note", "text": "n"}]}
    before = json.dumps(old, sort_keys=True)
    g = normalize(old)
    assert json.dumps(old, sort_keys=True) == before  # input not mutated
    assert g["created"] == "" and g["updated"] == "" and g["bookmarked"] is False
    assert g["app"] == "explorer" and g["app_icon"] is None
    assert g["settings"] == DEFAULT_SETTINGS
    s0 = g["steps"][0]
    assert s0["markers"] == [] and s0["crop"] is None and s0["image"] is None
    assert normalize(g) == g  # idempotent
    assert normalize({"id": "x", "title": "no dash", "steps": []})["app"] == ""
    custom = normalize({**old, "settings": {"toc": True}})["settings"]
    assert custom["toc"] is True and custom["click_color"] == "#FB923C"


def test_step_count_ignores_notes():
    assert step_count({"steps": [{"kind": "click"}, {"kind": "note"},
                                 {"kind": "type"}]}) == 2


def test_wrong_shape_guide_skipped():
    # valid JSON, wrong shape: must not blank the whole list or the search
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "a", steps=[{"id": "s1", "kind": "click", "text": "x"}])
        _seed(st, "b", steps=[None])
        _seed(st, "c", steps=["x"])
        _seed(st, "d", title=5)
        _seed(st, "e", created=5)
        _seed(st, "f", steps=[{"id": "s1", "kind": "click", "text": 5}])
        _seed(st, "g", settings=[1])
        assert [s["id"] for s in list_guides(st)] == ["a"]
        assert [s["id"] for s in list_guides(st, q="x")] == ["a"]
        trash_guide(st, "b")
        assert [t["id"] for t in list_trash(st)] == ["b"]  # listed by folder name
        assert save_guide(st, "a", {"title": "T", "steps": [None]}) is False


def test_save_guide_reports_write_failure():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1", title="before")
        (st / "g1" / "guide.json.tmp").mkdir()  # the temp file cannot be written
        assert save_guide(st, "g1", {"title": "after", "steps": []}) is False
        assert _load(st, "g1")["title"] == "before"


def _img_bytes(fmt: str) -> bytes:
    from io import BytesIO
    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(b, fmt)
    return b.getvalue()


def test_normalize_new_image_fields():
    g = normalize({"id": "x", "title": "A - b", "steps": [
        {"id": "s1", "kind": "click", "text": "t",
         "markers": [{"x": 1, "y": 2, "color": "#FB923C", "size": 44}]}]})
    s = g["steps"][0]
    assert s["annotations"] == [] and s["redactions"] == []
    assert s["markers"][0]["shape"] == "circle" and s["markers"][0]["size"] == 44
    assert g["settings"]["click_shape"] == "circle"
    assert g["settings"]["click_size"] == 44
    keep = normalize({**g, "steps": [
        {**s, "markers": [{**s["markers"][0], "shape": "rect"}]}]})
    assert keep["steps"][0]["markers"][0]["shape"] == "rect"
    assert normalize(g) == g


def test_wrong_shape_layers_skipped():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "a")
        _seed(st, "b", steps=[{"id": "s", "kind": "click", "text": "", "markers": "x"}])
        _seed(st, "c", steps=[{"id": "s", "kind": "click", "text": "", "annotations": [1]}])
        _seed(st, "d", steps=[{"id": "s", "kind": "click", "text": "", "redactions": {"x": 1}}])
        assert [s["id"] for s in list_guides(st)] == ["a"]


def test_image_kind():
    assert image_kind(_img_bytes("PNG")) == "png"
    assert image_kind(_img_bytes("JPEG")) == "jpg"
    assert image_kind(_img_bytes("GIF")) == "gif"
    assert image_kind(b"hello") is None and image_kind(b"") is None


def test_add_image_saves_only_real_images():
    import re
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1")
        gif = _img_bytes("GIF")
        n = add_image(st, "g1", gif)
        assert re.fullmatch(r"i[0-9a-f]{8}\.gif", n or ""), n
        assert (st / "g1" / n).read_bytes() == gif
        n2 = add_image(st, "g1", _img_bytes("PNG"))
        assert n2 and n2 != n and n2.endswith(".png")
        png = _img_bytes("PNG")
        assert add_image(st, "g1", b"<html>") is None
        assert add_image(st, "g1", b"") is None
        assert add_image(st, "g1", b"\x89PNG\r\n\x1a\n" + b"0" * MAX_IMAGE) is None
        assert add_image(st, "../x", png) is None
        assert add_image(st, "missing", png) is None
        assert sorted(f.name for f in (st / "g1").iterdir()) == sorted(["guide.json", n, n2])


def test_corrupt_guide_skipped():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "a")
        (st / "b").mkdir()
        (st / "b" / "guide.json").write_text('{"id": "b", "ti', encoding="utf-8")
        (st / "_tmp").mkdir()
        _seed(st, "_trash")  # a system folder that happens to hold a guide.json
        (st / "stray.txt").write_text("x", encoding="utf-8")
        assert [s["id"] for s in list_guides(st)] == ["a"]
        assert (st / "b" / "guide.json").exists()


def test_list_search_and_order():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "20261001-100000", title="Notepad - เก่า",
              created="2026-10-01T10:00:00",
              steps=[{"id": "s1", "kind": "click", "text": "บันทึกไฟล์"},
                     {"id": "s2", "kind": "note", "text": "หมายเหตุ"}])
        _seed(st, "20261010-100000", title="Excel - ใหม่",
              created="2026-10-10T10:00:00", bookmarked=True)
        assert [s["id"] for s in list_guides(st)] == \
            ["20261010-100000", "20261001-100000"]  # newest created first
        assert [s["id"] for s in list_guides(st, q="บันทึกไฟล์")] == \
            ["20261001-100000"]  # step text
        assert [s["id"] for s in list_guides(st, q="  EXCEL ")] == \
            ["20261010-100000"]  # casefold title
        assert [s["id"] for s in list_guides(st, bookmarked_only=True)] == \
            ["20261010-100000"]
        s = list_guides(st)[1]
        assert s["count"] == 1 and s["app"] == "Notepad"
        assert s["icon"] is False and s["ago"] != ""
        assert set(s) == {"id", "title", "created", "updated", "count", "app",
                          "icon", "bookmarked", "ago"}


def test_trash_restore_purge():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1", title="คู่มือหนึ่ง")
        assert trash_guide(st, "g1") is True
        assert not (st / "g1").exists()
        assert _load(st, "_trash", "g1")["deleted"]
        assert list_guides(st) == [] and list_guides(st, q="คู่มือหนึ่ง") == []
        assert [t["id"] for t in list_trash(st)] == ["g1"]
        assert restore_guide(st, "g1") is True
        assert "deleted" not in _load(st, "g1")
        assert [s["id"] for s in list_guides(st)] == ["g1"]

        calls = []
        trash_guide(st, "g1")
        assert purge_guide(st, "g1", recycle=_fake_recycle(calls)) is True
        assert calls == [st / "_trash" / "g1"]

        _seed(st, "g2")
        _seed(st, "g3")
        trash_guide(st, "g2")
        trash_guide(st, "g3")
        calls.clear()
        assert empty_trash(st, recycle=_fake_recycle(calls)) == 2 and len(calls) == 2
        assert list_trash(st) == []

        assert trash_guide(st, "_trash") is False
        assert trash_guide(st, "../x") is False
        assert trash_guide(st, "missing") is False


def test_restore_refuses_taken_id():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1", title="old")
        trash_guide(st, "g1")
        _seed(st, "g1", title="new")
        assert restore_guide(st, "g1") is False
        assert (st / "g1").exists() and (st / "_trash" / "g1").exists()
        assert _load(st, "g1")["title"] == "new"


def test_new_id_unique():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        t = time.mktime((2026, 10, 15, 12, 0, 0, 0, 0, -1))
        assert new_id(st, t) == "20261015-120000"
        (st / "20261015-120000").mkdir()
        (st / "_trash" / "20261015-120000-2").mkdir(parents=True)
        assert new_id(st, t) == "20261015-120000-3"


def test_duplicate_and_meta():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        folder = _seed(st, "g1", title="A", bookmarked=True,
                       steps=[{"id": "s1", "kind": "click", "text": "x",
                               "image": "s1.png"}])
        (folder / "s1.png").write_bytes(b"png")
        new = duplicate_guide(st, "g1")
        assert new and new != "g1" and (st / new / "s1.png").exists()
        c = _load(st, new)
        assert c["title"] == "A (สำเนา)" and c["id"] == new
        assert c["bookmarked"] is False
        assert c["created"] == c["updated"] and len(c["created"]) == 19
        new2 = duplicate_guide(st, new)
        assert new2 not in ("g1", new)
        assert _load(st, new2)["title"] == "A (สำเนา) (สำเนา)"

        before = _load(st, "g1").get("updated")
        assert update_meta(st, "g1", bookmarked=False) is True
        assert _load(st, "g1")["bookmarked"] is False
        assert _load(st, "g1").get("updated") == before
        assert update_meta(st, "g1", title="B") is True
        g = _load(st, "g1")
        assert g["title"] == "B" and g.get("updated") != before
        assert update_meta(st, "g1", title="   ") is False


def test_rename_keeps_app_of_old_guide():
    # old guides have no "app" field; it comes from the "App - ..." title
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1", title="Code - 15 ต.ค. 2569 15:23")
        assert update_meta(st, "g1", title="ชื่อใหม่") is True
        assert list_guides(st)[0]["app"] == "Code"


def test_save_guide_sets_id_and_updated_atomically():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1")
        assert save_guide(st, "g1", {"id": "evil", "title": "T", "steps": []})
        g = _load(st, "g1")
        assert g["id"] == "g1" and len(g["updated"]) == 19
        assert not list((st / "g1").glob("*.tmp"))
        assert save_guide(st, "g1", {"steps": "nope"}) is False
        assert save_guide(st, "missing", {"steps": []}) is False


def test_safe_name_rejects_drives_and_controls():
    from library import safe_name
    assert safe_name("a.png") and not safe_name("C:") and not safe_name("C:x.png")
    assert not safe_name("a\x00b") and not safe_name("..") and not safe_name("a/b")


def test_page_crud():
    import library as L
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1")
        p = L.create_page(st, "เริ่มงาน")
        assert L.safe_name(p["id"]) and p["sections"] == [] and p["settings"]["toc"] is True
        got = L.read_page(st, p["id"])
        assert got["title"] == "เริ่มงาน" and got["description"] == ""
        assert L.save_page(st, p["id"], {**got, "sections": [{"type": "text", "title": "ก", "text": "ข"}]})
        assert L.read_page(st, p["id"])["sections"][0]["text"] == "ข"
        assert [x["id"] for x in L.list_pages(st)] == [p["id"]] and L.list_pages(st)[0]["count"] == 0
        assert not L.save_page(st, p["id"], {**got, "sections": [{"type": "guide", "guide": "../x"}]})
        assert L.delete_page(st, p["id"]) and L.read_page(st, p["id"]) is None
        assert (st / "g1" / "guide.json").is_file()


def test_add_guide_once():
    import library as L
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1")
        pid = L.create_page(st, "t")["id"]
        assert L.add_guide_to_page(st, pid, "g1") == "added"
        assert L.add_guide_to_page(st, pid, "g1") == "exists"
        assert L.add_guide_to_page(st, "nope", "g1") is None
        assert L.add_guide_to_page(st, pid, "nope") is None
        assert L.list_pages(st)[0]["count"] == 1


def test_save_page_drops_duplicate_guides():
    import library as L
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        p = L.create_page(st, "t")
        g = {"type": "guide", "guide": "g1"}
        assert L.save_page(st, p["id"], {**p, "sections": [g, {"type": "text"}, g]})
        assert L.read_page(st, p["id"])["sections"] == [g, {"type": "text"}]


def test_page_count_skips_deleted_guides():
    import library as L
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1")
        p = L.create_page(st, "t")
        L.save_page(st, p["id"], {**p, "sections": [{"type": "guide", "guide": "g1"},
                                                    {"type": "guide", "guide": "gone"}]})
        assert L.list_pages(st)[0]["count"] == 1


def test_pages_hidden_from_guides():
    import library as L
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        _seed(st, "g1")
        L.create_page(st, "t")
        assert [g["id"] for g in list_guides(st)] == ["g1"] and list_trash(st) == []


def test_list_pages_skips_bad():
    import library as L
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        good = L.create_page(st, "ok")["id"]
        (st / "_pages" / "bad.json").write_text("{oops", encoding="utf-8")
        (st / "_pages" / "worse.json").write_text('{"title": "x", "sections": 5}', encoding="utf-8")
        (st / "_pages" / "odd.json").write_text('{"title": "b", "sections": [], "updated": 5}',
                                                encoding="utf-8")
        assert [p["id"] for p in L.list_pages(st)] == [good]
        assert L.read_page(st, "bad") is None and L.read_page(st, "worse") is None


_GA = {"id": "g1", "title": "ก", "steps": [{"id": "s1", "kind": "click", "text": "a"},
                                         {"id": "n", "kind": "note", "text": "x"},
                                         {"id": "s2", "kind": "click", "text": "b"}]}
_GB = {"id": "g2", "title": "ข", "steps": [{"id": "s1", "kind": "click", "text": "c"}]}


def test_compile_numbering_and_sections():
    import library as L
    page = {"id": "p1", "title": "P", "settings": dict(L.DEFAULT_PAGE_SETTINGS),
            "sections": [{"type": "guide", "guide": "g1"},
                         {"type": "text", "title": "หัวข้อ", "text": "เนื้อหา"},
                         {"type": "guide", "guide": "g2"}]}
    doc, missing = L.compile_page(page, {"g1": _GA, "g2": _GB})
    assert missing == 0 and doc["title"] == "P"
    assert [s["kind"] for s in doc["steps"]] == \
        ["section", "click", "note", "click", "section", "section", "click"]
    assert [s["id"] for s in doc["steps"]] == \
        ["sec0", "g1/s1", "g1/n", "g1/s2", "sec1", "sec2", "g2/s1"]
    assert doc["steps"][4]["body"] == "เนื้อหา" and doc["steps"][1]["gid"] == "g1"
    assert doc["steps"][0]["text"] == "ก"


def test_compile_skips_missing():
    import library as L
    page = {"id": "p1", "title": "P", "settings": {}, "sections": [{"type": "guide", "guide": "g1"}]}
    doc, missing = L.compile_page(page, {"g1": None})
    assert missing == 1 and doc["steps"] == \
        [{"id": "sec0", "kind": "section", "text": "คู่มือนี้ถูกลบแล้ว", "missing": True, "gid": "g1"}]


def test_compile_ids_unique():
    import library as L
    page = {"id": "p1", "title": "P", "settings": {},
            "sections": [{"type": "guide", "guide": "g2"}, {"type": "guide", "guide": "g3"}]}
    doc, _ = L.compile_page(page, {"g2": _GB, "g3": {**_GB, "id": "g3"}})
    ids = [s["id"] for s in doc["steps"]]
    assert len(ids) == len(set(ids)), ids
    # a folder renamed by hand may hold a dot: "a.b"+"c" must not meet "a"+"b.c"
    page["sections"] = [{"type": "guide", "guide": "a.b"}, {"type": "guide", "guide": "a"}]
    doc, _ = L.compile_page(page, {"a.b": {"steps": [{"id": "c", "kind": "click"}]},
                                   "a": {"steps": [{"id": "b.c", "kind": "click"}]}})
    ids = [s["id"] for s in doc["steps"]]
    assert len(ids) == len(set(ids)), ids


def test_settings_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        assert load_settings(st) == DEFAULT_APP_SETTINGS  # no file yet
        save_settings(st, view="list", bogus=1)
        assert load_settings(st) == {**DEFAULT_APP_SETTINGS, "view": "list"}
        (st / "settings.json").write_text("{bad", encoding="utf-8")
        assert load_settings(st) == DEFAULT_APP_SETTINGS  # corrupt -> defaults


def test_redact_settings_defaults_and_validation():
    import redact
    with tempfile.TemporaryDirectory() as d:
        st = Path(d)
        s = load_settings(st)
        assert s["redact_on"] is True
        assert s["redact_rules"] == list(redact.RULES)
        assert s["redact_custom"] == []
        save_settings(st, redact_rules=["email", "x"], redact_custom=[" acme ", ""])
        s = load_settings(st)
        assert s["redact_rules"] == ["email"] and s["redact_custom"] == ["acme"]
        # junk written by hand falls back to defaults
        (st / "settings.json").write_text('{"redact_on": "yes", "redact_rules": 5}',
                                          encoding="utf-8")
        s = load_settings(st)
        assert s["redact_on"] is True and s["redact_rules"] == list(redact.RULES)


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
