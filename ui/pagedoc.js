// A Page: several guides (and text blocks) in one document. The page file only
// references guides; view and export use the server's compiled document, where
// "section" entries open each guide and numbering restarts.
"use strict";

let PID = null, PG = null, PSAVET = null;
const goPage = (id, mode) => nav({pg: id, mode: mode || "view"});
const PAGE_SWITCHES = [["toc", "สารบัญ"], ["step_count", "จำนวนคู่มือ"],
  ["created", "วันที่สร้าง"], ["updated", "วันที่แก้ไขล่าสุด"]];

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
    return nav({page: "pages"});
  }
  document.title = "StepCap - " + PG.title;
  (mode === "edit" ? pageEdit : pageView)();
}

function pageView() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับไปที่ Pages">${ICON.back}</button>
      <div class="gtitle">${esc(PG.title)}</div>
      <button class="btn" id="edit">${ICON.edit} แก้ไข</button>
      <button class="btn dark" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody"><div id="rg"></div></div>`;
  document.getElementById("back").onclick = () => nav({page: "pages"});
  document.getElementById("edit").onclick = () => goPage(PID, "edit");
  document.getElementById("exp").onclick = e => { e.stopPropagation(); exportMenu(e.currentTarget, PID, "page"); };
  const doc = {...PG, steps: PG.steps.map(s => s.image ? {...s, _src: imgUrl(s.gid, s.image)} : s)};
  renderGuide(doc, document.getElementById("rg"));
  startStatusPoll(() => {}, 1000);
  if (PG.redact_notes?.length) toast(PG.redact_notes.join(" · "), 10000);
}

// ---- edit
function pageEdit() {
  app.innerHTML = `<header class="gtop">
      <button class="icon-btn" id="back" title="กลับไปที่ Pages">${ICON.back}</button>
      <input id="ptitle" class="gtitle" type="text" value="${esc(PG.title)}">
      <button class="btn dark" id="done">${ICON.done} เสร็จสิ้น</button>
      <button class="btn" id="exp">${ICON.export} ส่งออก</button>
    </header><div class="gbody"><div class="pedit">
      <textarea id="pdesc" class="dlg-in" rows="2" placeholder="คำอธิบาย (ไม่ใส่ก็ได้)">${esc(PG.description)}</textarea>
      <div class="pset">${PAGE_SWITCHES.map(([k, l]) => `<label class="chk">
        <input type="checkbox" data-k="${k}" ${PG.settings[k] ? "checked" : ""}> ${l}</label>`).join("")}</div>
      <div id="psecs"></div>
      <div class="padd"><button type="button" class="btn" id="addguide">+ เพิ่มคู่มือ</button>
        <button type="button" class="btn" id="addtext">+ เพิ่มข้อความ</button></div>
    </div></div>`;
  const leave = async to => { if (await pageFlush()) to(); };
  document.getElementById("back").onclick = () => leave(() => nav({page: "pages"}));
  document.getElementById("done").onclick = () => leave(() => goPage(PID, "view"));
  document.getElementById("exp").onclick = async e => {
    e.stopPropagation();
    const b = e.currentTarget;
    if (await pageFlush()) exportMenu(b, PID, "page");
  };
  document.getElementById("ptitle").oninput = e => { PG.title = e.target.value; pageSave(); };
  document.getElementById("pdesc").oninput = e => { PG.description = e.target.value; pageSave(); };
  document.querySelectorAll(".pset [data-k]").forEach(b => b.onchange = () => {
    PG.settings[b.dataset.k] = b.checked; pageSave();
  });
  document.getElementById("addguide").onclick = pickGuides;
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
    const btns = `<div class="pbtns">
      <button type="button" class="icon-btn" data-act="up" title="เลื่อนขึ้น" ${i ? "" : "disabled"}>↑</button>
      <button type="button" class="icon-btn" data-act="down" title="เลื่อนลง" ${i < last ? "" : "disabled"}>↓</button>
      <button type="button" class="icon-btn" data-act="del" title="นำออกจาก Page">${ICON.trash}</button></div>`;
    if (s.type === "text") return `<div class="psec text" data-i="${i}">
      <div class="pmain"><input class="dlg-in" data-f="title" placeholder="หัวข้อ" value="${esc(s.title)}">
      <textarea class="dlg-in" data-f="text" rows="3" placeholder="ข้อความ">${esc(s.text)}</textarea></div>${btns}</div>`;
    const g = PG.guides[s.guide];
    return `<div class="psec" data-i="${i}" data-gid="${esc(s.guide)}"><div class="pmain">${g
      ? `${ICON.docs}<a href="#" data-act="open">${esc(g.title || s.guide)}</a>`
      : `<span class="muted">คู่มือนี้ถูกลบแล้ว</span>`}</div>${btns}</div>`;
  }).join("") || `<p class="muted">ยังไม่มีคู่มือใน Page นี้</p>`;
  box.querySelectorAll(".psec").forEach(row => {
    const i = +row.dataset.i;
    const move = d => {
      const [x] = PG.sections.splice(i, 1);
      PG.sections.splice(i + d, 0, x);
      renderSections(); pageSave();
    };
    row.querySelector("[data-act=up]").onclick = () => move(-1);
    row.querySelector("[data-act=down]").onclick = () => move(1);
    row.querySelector("[data-act=del]").onclick = () => { PG.sections.splice(i, 1); renderSections(); pageSave(); };
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
  const d = await _dialog(`<p class="dlg-t">เพิ่มคู่มือ</p>
    <input class="dlg-in" type="text" id="pq" placeholder="ค้นหา">
    <div class="plist">${all.map(g => `<label class="chk prow" data-t="${esc(g.title.toLowerCase())}">
      <input type="checkbox" data-gid="${esc(g.id)}" ${have.has(g.id) ? "checked disabled" : ""}>
      ${esc(g.title)}</label>`).join("") || `<p class="muted">ยังไม่มีคู่มือ</p>`}</div>`, "เพิ่ม", "dark", dlg => {
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

// Autosave, same rules as a guide: a failed save keeps the edits and retries.
function pageSave() { clearTimeout(PSAVET); PSAVET = setTimeout(pageSaveNow, 500); }
async function pageSaveNow() {
  clearTimeout(PSAVET); PSAVET = null;
  let ok = false;
  try { ok = (await post("/api/page/" + encodeURIComponent(PID), PG)).ok; } catch { /* offline */ }
  if (!ok) { toast("บันทึกไม่สำเร็จ จะลองใหม่อัตโนมัติ"); PSAVET = setTimeout(pageSaveNow, 3000); }
  return ok;
}
const pageFlush = async () => !PSAVET || await pageSaveNow();

// ---- the Pages screen (sidebar) and "add to page" from a guide
async function renderPages(c) {
  const my = ++RENDER;
  const items = await getJSON("/api/pages");
  if (my !== RENDER) return;
  c.innerHTML = `<div class="sec-h"><h2>Pages</h2>
      <button type="button" class="btn dark" id="newpage">+ สร้าง Page</button></div>
    <p class="muted">รวมหลายคู่มือเป็นเอกสารเดียว ส่งต่อหรือส่งออกได้ครั้งเดียว</p>
    ${items.length ? `<div class="pcards">${items.map(p => `<div class="pcard" data-id="${esc(p.id)}">
        <div class="pc-title">${esc(p.title)}</div>
        <div class="muted small">${p.count} คู่มือ · ${esc(p.ago || "")}</div>
        <button type="button" class="tool more" title="เพิ่มเติม">${ICON.more}</button></div>`).join("")}</div>`
      : `<p class="muted">ยังไม่มี Page</p>`}`;
  c.querySelector("#newpage").onclick = async () => {
    const title = await uiPrompt("ชื่อ Page", "");
    if (title === null || !title.trim()) return;
    const p = await (await post("/api/pages", {title: title.trim()})).json();
    goPage(p.id, "edit");
  };
  c.querySelectorAll(".pcard").forEach(card => {
    const id = card.dataset.id, p = items.find(x => x.id === id);
    card.onclick = () => goPage(id, "view");
    card.querySelector(".more").onclick = e => {
      e.stopPropagation();
      const anchor = e.currentTarget, url = "/api/page/" + encodeURIComponent(id);
      popMenu(anchor, [
        {label: "เปิด", run: () => goPage(id, "view")},
        {label: "เปลี่ยนชื่อ", run: async () => {
          const title = await uiPrompt("เปลี่ยนชื่อ Page", p.title);
          if (title === null || !title.trim()) return;
          const page = await getJSON(url);
          if (!(await post(url, {...page, title: title.trim()})).ok) toast(FAILED);
          refresh();
        }},
        {label: "ส่งออก", run: () => exportMenu(anchor, id, "page")},
        {label: "ลบ", danger: true, run: async () => {
          if (!(await uiConfirm("ลบ Page นี้? คู่มือข้างในไม่ถูกลบ", "ลบ"))) return;
          toast((await post(url + "/delete")).ok ? "ลบ Page แล้ว" : FAILED);
          refresh();
        }},
      ]);
    };
  });
}

async function addToPageMenu(anchor, gid) {
  const pages = await getJSON("/api/pages");
  const add = async (pid, title) => {
    const r = await post("/api/page/" + encodeURIComponent(pid) + "/add", {guide: gid});
    const res = r.ok ? (await r.json()).result : null;
    toast(res === "added" ? `เพิ่มลงใน ${title} แล้ว` : res === "exists" ? "มีอยู่ใน Page นี้แล้ว" : FAILED);
  };
  popMenu(anchor, [
    ...pages.map(p => ({label: p.title, run: () => add(p.id, p.title)})),
    {label: "+ สร้าง Page ใหม่", run: async () => {
      const title = await uiPrompt("ชื่อ Page", STATE?.title || "");
      if (title === null || !title.trim()) return;
      const p = await (await post("/api/pages", {title: title.trim()})).json();
      add(p.id, p.title);
    }},
  ]);
}
