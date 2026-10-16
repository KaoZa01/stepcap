// First-time tours: the page dims, a ring circles one control at a time and a
// box says what it does. Look-only: the page underneath takes no clicks while
// it's open. Each screen's tour shows once (settings tours_seen); it waits for
// a later visit while recording, under the redaction cover, in a narrow
// window, or when the first thing it points at isn't on the page.
"use strict";

const _q = sel => () => document.querySelector(sel);
const TOURS = {
  home: [
    {target: _q("#recbtn"), title: "เริ่มบันทึกที่นี่",
     text: "กดแล้วเลือกจอ แล้วกด เริ่มบันทึก หน้าต่างนี้จะย่อลง ให้ทำงานตามปกติ แล้วกด หยุดบันทึก ที่แผงมุมขวาล่าง หรือกด Ctrl+Alt+R"},
    {target: () => [...document.querySelectorAll(".card .title, .row .r-title")]
       .find(e => e.textContent.startsWith("ตัวอย่าง:"))?.closest(".card, .row") || null,
     title: "ดูตัวอย่างก่อน",
     text: "เปิดคู่มือนี้เพื่อดูว่าคู่มือที่เสร็จแล้วหน้าตาเป็นอย่างไร ลองแก้หรือส่งออกได้ตามสบาย"},
    {target: _q(".menu"), title: "เมนูอื่น ๆ",
     text: "Page ใช้รวมหลายคู่มือเป็นเอกสารเดียว ถังขยะกู้คืนได้ ตั้งค่ามีที่เก็บไฟล์และปุ่มดูคำแนะนำนี้อีกครั้ง"},
  ],
  edit: [],
};

let TOUR_OPEN = false;

// Shows a screen's tour if it's due, then remembers it was seen.
async function maybeTour(name) {
  const stops = TOURS[name];
  if (TOUR_OPEN || !stops?.length) return;
  TOUR_OPEN = true;  // held across the checks: a re-render can't start a second one
  try {
    const due = () => innerWidth >= 760 && !document.getElementById("redcover");
    if (!due()) return;
    let s, st;
    try { [s, st] = await Promise.all([getJSON("/api/settings"), getJSON("/api/status")]); } catch { return; }
    if (s.tours_seen.includes(name) || st.recording || !due() || !stops[0].target()) return;
    await runTour(stops);
    let seen = [];
    try { seen = (await getJSON("/api/settings")).tours_seen; } catch { /* keep going */ }
    await postOk("/api/settings", {tours_seen: [...new Set([...seen, name])]});
  } finally {
    TOUR_OPEN = false;
  }
}

// Steps through stops ({target() -> Element|null, title, text}); a stop with
// nothing to point at is left out. Resolves when skipped or finished.
function runTour(stops) {
  return new Promise(resolve => {
    const live = stops.filter(s => s.target());
    if (!live.length) return resolve();
    const opener = document.activeElement;
    const mk = cls => Object.assign(document.createElement("div"), {className: cls});
    const shade = mk("tour-shade"), ring = mk("tour-ring"), box = mk("tour-box");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-labelledby", "tour-t");
    document.body.append(shade, ring, box);
    let i = 0;

    // ring on the target (found again each time: the page may have re-rendered),
    // box under it when it fits, else above, kept 12px inside the window
    const place = () => {
      const t = live[i].target();
      if (!t) return;
      const r = t.getBoundingClientRect(), pad = 4, gap = 12;
      Object.assign(ring.style, {left: r.left - pad + "px", top: r.top - pad + "px",
        width: r.width + 2 * pad + "px", height: r.height + 2 * pad + "px"});
      const h = box.offsetHeight, w = box.offsetWidth;
      const top = r.bottom + gap + h <= innerHeight - gap ? r.bottom + gap : Math.max(gap, r.top - gap - h);
      box.style.top = top + "px";
      box.style.left = Math.max(gap, Math.min(r.left, innerWidth - w - gap)) + "px";
    };
    const show = n => {
      i = n;
      const s = live[i], last = i === live.length - 1;
      s.target()?.scrollIntoView({block: "nearest"});
      box.innerHTML = `<p class="tour-title" id="tour-t">${esc(s.title)}</p><p class="tour-text">${esc(s.text)}</p>
        <div class="tour-foot"><span class="tour-count">${i + 1}/${live.length}</span>
          <button type="button" class="btn" data-t="skip">ข้าม</button>
          <button type="button" class="btn" data-t="back" ${i ? "" : "disabled"}>ย้อนกลับ</button>
          <button type="button" class="btn dark" data-t="next">${last ? "เสร็จสิ้น" : "ถัดไป"}</button></div>`;
      box.querySelector("[data-t=skip]").onclick = close;
      box.querySelector("[data-t=back]").onclick = () => show(i - 1);
      box.querySelector("[data-t=next]").onclick = () => last ? close() : show(i + 1);
      place();
      box.querySelector("[data-t=next]").focus();
    };
    // the tour's keys win over the page's (record menu, editor, popMenu):
    // caught first, on window, and not passed on
    const keys = e => {
      if (e.key === "Escape") {
        e.preventDefault(); e.stopImmediatePropagation(); close();
      } else if (e.key === "Enter") {
        e.preventDefault(); e.stopImmediatePropagation();
        const b = box.contains(document.activeElement) && document.activeElement.closest("button");
        (b && !b.disabled ? b : box.querySelector("[data-t=next]")).click();
      } else if (e.key === "Tab") {  // focus stays in the box
        const bs = [...box.querySelectorAll("button:not(:disabled)")];
        const at = bs.indexOf(document.activeElement);
        e.preventDefault(); e.stopImmediatePropagation();
        bs[(at + (e.shiftKey ? -1 : 1) + bs.length) % bs.length].focus();
      }
    };
    function close() {
      removeEventListener("keydown", keys, true);
      removeEventListener("resize", place);
      removeEventListener("scroll", place, true);
      shade.remove(); ring.remove(); box.remove();
      if (opener?.isConnected) opener.focus?.();
      resolve();
    }
    addEventListener("keydown", keys, true);
    addEventListener("resize", place);
    addEventListener("scroll", place, true);
    show(0);
  });
}
