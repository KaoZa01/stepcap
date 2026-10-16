// A Page: several guides (and text blocks) in one document. The page file only
// references guides; view and export use the server's compiled document, where
// "section" entries open each guide and numbering restarts.
"use strict";

let PID = null, PG = null, PSAVET = null;
const goPage = (id, mode) => nav({pg: id, mode: mode || "view"});
const PAGE_SWITCHES = [["toc", tr("สารบัญ")], ["step_count", tr("จำนวนคู่มือ")],
  ["created", tr("วันที่สร้าง")], ["updated", tr("วันที่แก้ไขล่าสุด")]];

async function pageDocPage(id, mode) {
  PID = id;
  let r;
  try {
    if (mode === "edit") {
      r = await api("/api/page/" + encodeURIComponent(id));
    } else {
      while ((r = await api("/api/page/" + encodeURIComponent(id) + "/doc")).status === 409) {
        COVER_HOLD = true;
        redactCover([0, 0]);  // one of its guides is still being auto-redacted
        await new Promise(res => setTimeout(res, 500));
      }
      if (COVER_HOLD) { COVER_HOLD = false; redactCover(null); }
    }
    if (!r.ok) throw new Error(r.status);
    PG = await r.json();
  } catch {
    return nav({page: "pages", msg: "page"});
  }
  document.title = "StepCap - " + PG.title;
  (mode === "edit" ? pageEdit : pageView)();
}

function pageView() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="${tr("กลับไปที่ Pages")}" aria-label="${tr("กลับไปที่ Pages")}">${ICON.back}</button>
      <div class="gtitle">${esc(PG.title)}</div>
      <button class="btn" id="edit">${ICON.edit} ${tr("แก้ไข")}</button>
      <button class="btn dark" id="exp">${ICON.export} ${tr("ส่งออก")}</button>
    </header><div class="gbody"><div id="rg"></div></div>`;
  document.getElementById("back").onclick = () => nav({page: "pages"});
  document.getElementById("edit").onclick = () => goPage(PID, "edit");
  document.getElementById("exp").onclick = e => { e.stopPropagation(); exportMenu(e.currentTarget, PID, "page"); };
  const doc = {...PG, steps: PG.steps.map(s => s.image ? {...s, _src: imgUrl(s.gid, s.image)} : s)};
  renderGuide(doc, document.getElementById("rg"));
  startStatusPoll(() => {}, 1000);
  if (PG.redact_notes?.length) toastErr(PG.redact_notes.join(" · "), 10000);
}

// ---- edit
function pageEdit() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="${tr("กลับไปที่ Pages")}" aria-label="${tr("กลับไปที่ Pages")}">${ICON.back}</button>
      <input id="ptitle" class="gtitle" type="text" value="${esc(PG.title)}" aria-label="${tr("ชื่อ Page")}">
      <button class="btn" id="done">${ICON.done} ${tr("เสร็จสิ้น")}</button>
      <button class="btn dark" id="exp">${ICON.export} ${tr("ส่งออก")}</button>
    </header><div class="gbody"><div class="pedit">
      <textarea id="pdesc" class="dlg-in" rows="2" placeholder="${tr("คำอธิบาย (ไม่ใส่ก็ได้)")}" aria-label="${tr("คำอธิบาย")}">${esc(PG.description)}</textarea>
      <div class="pset">${PAGE_SWITCHES.map(([k, l]) => `<label class="swlabel"><span class="switch">
        <input type="checkbox" data-k="${k}" ${PG.settings[k] ? "checked" : ""}><span></span></span>${l}</label>`).join("")}</div>
      <div id="psecs"></div>
      <div class="padd"><button type="button" class="btn" id="addguide">${ICON.plus} ${tr("เพิ่มคู่มือ")}</button>
        <button type="button" class="btn" id="addtext">${ICON.plus} ${tr("เพิ่มข้อความ")}</button></div>
    </div></div>`;
  const drop = () => { clearTimeout(PSAVET); PSAVET = null; PSAVE_FAILING = false; };
  const leave = to => leaveEdit(pageFlush, drop, to);
  document.getElementById("back").onclick = () => leave(() => nav({page: "pages"}));
  document.getElementById("done").onclick = () => leave(() => goPage(PID, "view"));
  document.getElementById("exp").onclick = async e => {
    e.stopPropagation();
    const b = e.currentTarget;
    if (await pageFlush()) exportMenu(b, PID, "page");
    else toastErr(tr("ยังบันทึกการแก้ไขไม่ได้ จึงยังส่งออกไม่ได้ ลองใหม่อีกครั้ง"));
  };
  document.getElementById("ptitle").oninput = e => { PG.title = e.target.value; pageSave(); };
  document.getElementById("pdesc").oninput = e => { PG.description = e.target.value; pageSave(); };
  document.querySelectorAll(".pset [data-k]").forEach(b => b.onchange = () => {
    PG.settings[b.dataset.k] = b.checked; pageSave();
  });
  document.getElementById("addguide").onclick = e => busy(e.currentTarget, pickGuides);
  document.getElementById("addtext").onclick = () => {
    PG.sections.push({type: "text", title: "", text: ""});
    renderSections(); pageSave();
  };
  renderSections();
  startStatusPoll(() => {}, 1000, pageFlush);
}

function renderSections() {
  const box = document.getElementById("psecs");
  const last = PG.sections.length - 1;
  box.innerHTML = PG.sections.map((s, i) => {
    const ib = (act, label, icon, on = true) => `<button type="button" class="icon-btn" data-act="${act}"
      title="${label}" aria-label="${label}" ${on ? "" : "disabled"}>${icon}</button>`;
    const btns = `<div class="pbtns">${ib("up", tr("เลื่อนขึ้น"), ICON.up, i > 0)}${ib("down", tr("เลื่อนลง"), ICON.down, i < last)}
      ${ib("del", tr("นำออกจาก Page"), ICON.trash)}</div>`;
    if (s.type === "text") return `<div class="psec text" data-i="${i}">
      <div class="pmain"><input class="dlg-in" data-f="title" placeholder="${tr("หัวข้อ")}" aria-label="${tr("หัวข้อ")}" value="${esc(s.title)}">
      <textarea class="dlg-in" data-f="text" rows="3" placeholder="${tr("ข้อความ")}" aria-label="${tr("ข้อความ")}">${esc(s.text)}</textarea></div>${btns}</div>`;
    const g = PG.guides[s.guide];
    return `<div class="psec" data-i="${i}" data-gid="${esc(s.guide)}"><div class="pmain">${g
      ? `${ICON.docs}<a href="#" data-act="open">${esc(g.title || s.guide)}</a>`
      : `<span class="muted">${tr("คู่มือนี้ถูกลบแล้ว")}</span>`}</div>${btns}</div>`;
  }).join("") || `<p class="empty">${tr("ยังไม่มีคู่มือใน Page นี้ กด เพิ่มคู่มือ ด้านล่าง")}</p>`;
  box.querySelectorAll(".psec").forEach(row => {
    const i = +row.dataset.i;
    const move = (d, act) => {
      const [x] = PG.sections.splice(i, 1);
      PG.sections.splice(i + d, 0, x);
      renderSections(); pageSave();
      const b = document.querySelector(`.psec[data-i="${i + d}"] [data-act="${act}"]`);
      (b && !b.disabled ? b : document.querySelector(`.psec[data-i="${i + d}"] [data-act="del"]`))?.focus();
    };
    row.querySelector("[data-act=up]").onclick = () => move(-1, "up");
    row.querySelector("[data-act=down]").onclick = () => move(1, "down");
    row.querySelector("[data-act=del]").onclick = async () => {
      const sec = PG.sections[i];  // typed text is lost on removal: ask first
      if (sec.type === "text" && (sec.title || sec.text).trim() &&
          !(await uiConfirm(tr("นำข้อความนี้ออก? ข้อความที่พิมพ์ไว้จะหายไป"), tr("นำออก")))) return;
      PG.sections.splice(i, 1); renderSections(); pageSave();
    };
    row.querySelector("[data-act=open]")?.addEventListener("click", async e => {
      e.preventDefault();
      if (await pageFlush()) goGuide(row.dataset.gid, "view");
    });
    row.querySelectorAll("[data-f]").forEach(f => f.oninput = () => {
      PG.sections[i][f.dataset.f] = f.value; pageSave();
    });
  });
}

// Pick guides to append; ones already on the page can't be picked again.
async function pickGuides() {
  const all = await getJSON("/api/guides");
  const have = new Set(PG.sections.filter(s => s.type === "guide").map(s => s.guide));
  const d = await _dialog(`<p class="dlg-t">${tr("เพิ่มคู่มือ")}</p>
    <input class="dlg-in" type="text" id="pq" placeholder="${tr("ค้นหา")}">
    <div class="plist">${all.filter(g => !g.broken).map(g => `<label class="chk prow" data-t="${esc(g.title.toLowerCase())}">
      <input type="checkbox" data-gid="${esc(g.id)}" ${have.has(g.id) ? "checked disabled" : ""}>
      <span>${esc(g.title)} <span class="pmeta">· ${tr("{n} ขั้นตอน", {n: g.count})} · ${esc(g.ago)}</span></span></label>`).join("")
      || `<p class="muted">${tr("ยังไม่มีคู่มือ")}</p>`}</div>`, tr("เพิ่ม"), "dark", dlg => {
    const q = dlg.querySelector("#pq");
    q.oninput = () => dlg.querySelectorAll(".prow").forEach(r =>
      r.hidden = !r.dataset.t.includes(q.value.trim().toLowerCase()));
    q.focus();
  });
  if (!d) return;
  const picked = [...d.querySelectorAll("[data-gid]:checked:not(:disabled)")].map(b => b.dataset.gid);
  for (const gid of picked) {
    PG.sections.push({type: "guide", guide: gid});
    PG.guides[gid] = {title: all.find(g => g.id === gid).title};
  }
  if (picked.length) { renderSections(); pageSave(); }
}

// Autosave, same rules as a guide: a failed save keeps the edits, says so once, and retries.
let PSAVE_FAILING = false;
function pageSave() { clearTimeout(PSAVET); PSAVET = setTimeout(pageSaveNow, 500); }
async function pageSaveNow() {
  clearTimeout(PSAVET); PSAVET = null;
  const ok = await postOk("/api/page/" + encodeURIComponent(PID), PG);
  if (!ok) {
    if (!PSAVE_FAILING) toastErr(tr("บันทึกไม่สำเร็จ จะลองใหม่อัตโนมัติ"));
    PSAVE_FAILING = true;
    PSAVET = setTimeout(pageSaveNow, 3000);
  } else if (PSAVE_FAILING) {
    PSAVE_FAILING = false;
    toast(tr("บันทึกแล้ว"));
  }
  return ok;
}
const pageFlush = async () => !PSAVET || await pageSaveNow();

// ---- the Pages screen (sidebar) and "add to page" from a guide
async function renderPages(c) {
  const my = ++RENDER;
  const items = await getJSON("/api/pages");
  if (my !== RENDER) return;
  c.innerHTML = `<div class="sec-h"><h2>Pages</h2>
      <button type="button" class="btn" id="newpage">${ICON.plus} ${tr("สร้าง Page")}</button></div>
    <p class="muted">${tr("รวมหลายคู่มือเป็นเอกสารเดียว ส่งต่อหรือส่งออกได้ครั้งเดียว")}</p>
    ${items.length ? `<div class="pcards">${items.map(p => `<div class="pcard" data-id="${esc(p.id)}">
        <div class="pc-title">${esc(p.title)}</div>
        <div class="muted small">${tr("{n} คู่มือ", {n: p.count})} · ${esc(p.ago || "")}</div>
        <button type="button" class="tool more" title="${tr("เพิ่มเติม")}" aria-label="${tr("เพิ่มเติม")}">${ICON.more}</button></div>`).join("")}</div>`
      : `<p class="empty">${tr("ยังไม่มี Page กด สร้าง Page เพื่อรวมหลายคู่มือเป็นเอกสารเดียว")}</p>`}`;
  c.querySelector("#newpage").onclick = e => busy(e.currentTarget, async () => {
    const title = await uiPrompt(tr("ชื่อ Page"), "");
    if (title === null || !title.trim()) return;
    const id = await newPage(title.trim());
    if (id) goPage(id, "edit");
  });
  c.querySelectorAll(".pcard").forEach(card => {
    const id = card.dataset.id, p = items.find(x => x.id === id);
    activatable(card, () => goPage(id, "view"), p.title);
    card.querySelector(".more").onclick = e => {
      e.stopPropagation();
      const anchor = e.currentTarget, url = "/api/page/" + encodeURIComponent(id);
      popMenu(anchor, [
        {label: tr("เปิด"), run: () => goPage(id, "view")},
        {label: tr("เปลี่ยนชื่อ"), run: async () => {
          const title = await uiPrompt(tr("เปลี่ยนชื่อ Page"), p.title);
          if (title === null || !title.trim()) return;
          let ok = false;
          try { ok = await postOk(url, {...(await getJSON(url)), title: title.trim()}); } catch { /* gone */ }
          if (ok) toast(tr("เปลี่ยนชื่อแล้ว")); else toastErr(FAILED);
          refresh();
        }},
        {label: tr("ส่งออก"), run: () => exportMenu(anchor, id, "page")},
        {label: tr("ลบ"), danger: true, run: async () => {
          if (!(await uiConfirm(tr("ลบ Page นี้? คู่มือข้างในไม่ถูกลบ"), tr("ลบ")))) return;
          if (await postOk(url + "/delete")) toast(tr("ลบ Page แล้ว")); else toastErr(FAILED);
          refresh();
        }},
      ]);
    };
  });
}

// The new page's id, or null (and says so) when it couldn't be made.
async function newPage(title) {
  try {
    const r = await post("/api/pages", {title});
    if (r.ok) return (await r.json()).id;
  } catch { /* offline */ }
  toastErr(FAILED);
  return null;
}

async function addToPageMenu(anchor, gid) {
  let pages;
  try { pages = await getJSON("/api/pages"); } catch { return toastErr(FAILED); }
  const add = async (pid, title) => {
    let res = null;
    try {
      const r = await post("/api/page/" + encodeURIComponent(pid) + "/add", {guide: gid});
      res = r.ok ? (await r.json()).result : null;
    } catch { /* offline */ }
    if (res) toast(res === "added" ? tr("เพิ่มลงใน {title} แล้ว", {title}) : tr("มีอยู่ใน Page นี้แล้ว"));
    else toastErr(FAILED);
  };
  popMenu(anchor, [
    ...pages.map(p => ({label: p.title, run: () => add(p.id, p.title)})),
    {label: "+ " + tr("สร้าง Page ใหม่"), run: async () => {
      const title = await uiPrompt(tr("ชื่อ Page"), STATE?.title || "");
      if (title === null || !title.trim()) return;
      const id = await newPage(title.trim());
      if (id) add(id, title.trim());
    }},
  ]);
}
