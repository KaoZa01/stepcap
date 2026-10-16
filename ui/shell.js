// The app shell: sidebar, top bar with the record menu, banners, and the
// Home / คู่มือทั้งหมด / ถังขยะ / ตั้งค่า pages (rendered in place).
"use strict";

const PAGES = {
  home: {name: tr("หน้าแรก"), icon: "home", render: renderHome},
  all: {name: tr("คู่มือทั้งหมด"), icon: "docs", render: renderAll},
  pages: {name: "Pages", icon: "page", render: renderPages},
  trash: {name: tr("ถังขยะ"), icon: "trash", render: renderTrash},
  settings: {name: tr("ตั้งค่า"), icon: "settings", render: renderSettings},
};
let PAGE = "home", QTEXT = "", VIEW = "grid", BM_ONLY = false, STATUS = null, RENDER = 0;

async function shellPage(page) {
  document.title = "StepCap";
  document.getElementById("app").innerHTML = `<div class="shell">
    <aside class="side">
      <div class="logo">${LOGO}<span>StepCap</span></div>
      <label class="search">${ICON.search}<input id="q" type="search" placeholder="${tr("ค้นหา")}" autocomplete="off"></label>
      <nav class="menu">${Object.entries(PAGES).map(([k, p]) =>
        `<button type="button" data-page="${k}">${ICON[p.icon]}<span>${esc(p.name)}</span></button>`).join("")}</nav>
    </aside>
    <div class="main">
      <header class="top"><div class="crumb" id="crumb"></div>
        <div class="rec-wrap"><button id="recbtn" class="btn dark">${ICON.plus} ${tr("บันทึกใหม่")}</button>
          <div id="recmenu" class="pop" hidden></div></div></header>
      <div class="scroll"><div class="content"><div id="banners"></div><div id="content"></div></div></div>
    </div></div>`;
  document.querySelectorAll(".menu button").forEach(a => a.onclick = () => {
    if (a.dataset.page !== "all") { QTEXT = ""; document.getElementById("q").value = ""; }
    go(a.dataset.page);
  });
  let debounce = null;
  document.getElementById("q").oninput = e => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { QTEXT = e.target.value; go("all"); }, 200);
  };
  document.getElementById("recbtn").onclick = onRecButton;
  document.addEventListener("click", e => {
    if (!e.target.closest(".rec-wrap")) document.getElementById("recmenu").hidden = true;
  });
  document.addEventListener("keydown", e => {
    const m = document.getElementById("recmenu");
    if (e.key !== "Escape" || !m || m.hidden) return;
    m.hidden = true;
    document.getElementById("recbtn").focus();
  });
  try { VIEW = (await getJSON("/api/settings")).view || "grid"; } catch { /* keep default */ }
  go(PAGES[page] ? page : "home");
  startStatusPoll(applyStatus, 500);
}

function go(page) {
  PAGE = page;
  history.replaceState(null, "", "?" + new URLSearchParams({t: T, page}).toString());
  document.querySelectorAll(".menu button").forEach(a => {
    a.classList.toggle("on", a.dataset.page === page);
    if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  const p = PAGES[page];
  document.getElementById("crumb").innerHTML = `${ICON[p.icon]}<span>${esc(p.name)}</span>`;
  refresh();
}
// A list that can't load says so, with a way to try again, instead of a blank page.
const refresh = () => {
  const c = document.getElementById("content");
  return PAGES[PAGE].render(c).catch(() => {
    c.innerHTML = `<div class="empty">${tr("โหลดข้อมูลไม่สำเร็จ")}<br><br>
      <button type="button" class="btn" id="retry">${tr("ลองใหม่")}</button></div>`;
    c.querySelector("#retry").onclick = refresh;
  });
};

// ---------------------------------------------------------------- status
function applyStatus(st) {
  STATUS = st;
  const b = document.getElementById("recbtn");
  if (!b) return;
  const rec = st.recording;
  if (b.dataset.rec !== String(rec)) {
    b.dataset.rec = String(rec);
    b.className = "btn " + (rec ? "red" : "dark");
    b.innerHTML = rec ? `${ICON.stop} ${tr("หยุดบันทึก")}` : `${ICON.plus} ${tr("บันทึกใหม่")}`;
  }
  renderBanners(st);
}

let bannerSig = "";
function renderBanners(st) {
  const sig = JSON.stringify([st.hooks_ok, st.hook_error, st.recording, st.paused, st.steps, st.pending]);
  if (sig === bannerSig) return;
  bannerSig = sig;
  let h = "";
  if (!st.hooks_ok)
    h += `<div class="banner warn">${tr("ตัวดักเมาส์/คีย์บอร์ดทำงานไม่ได้ (รหัส {code}) ปิดแล้วเปิด StepCap ใหม่", {code: esc(st.hook_error)})}</div>`;
  if (st.recording) {
    const tail = st.steps.slice(-5), first = st.steps.length - tail.length + 1;
    h += `<div class="banner rec"><div class="rec-h">
        <b class="${st.paused ? "paused" : "live"}">${st.paused ? "⏸ " + tr("พักอยู่") : "● " + tr("กำลังบันทึก")}</b>
        <span>${tr("{n} ขั้นตอน", {n: st.steps.length})}</span><span class="sp"></span>
        <button class="btn" data-act="pause">${st.paused ? tr("ทำต่อ") : tr("พัก")}</button>
        <button class="btn red" data-act="stop">${tr("หยุด")}</button></div>
      ${tail.length ? `<ol start="${first}">${tail.map(s => `<li>${esc(s.text)}</li>`).join("")}</ol>` : ""}
      ${st.pending ? `<div class="pending">… ${esc(st.pending)}</div>` : ""}
      ${!st.steps.length && !st.pending ? `<div class="pending">${tr("ยังไม่มีขั้นตอน เริ่มคลิกได้เลย")}</div>` : ""}</div>`;
  }
  const el = document.getElementById("banners");
  el.innerHTML = h;
  el.querySelector('[data-act="pause"]')?.addEventListener("click", e =>
    busy(e.currentTarget, async () => { await postOk("/api/pause"); TICK(); }));
  el.querySelector('[data-act="stop"]')?.addEventListener("click", e => busy(e.currentTarget, stopRecording));
}

async function stopRecording() {
  let r = {};
  try { r = await (await post("/api/stop")).json(); } catch { toastErr(tr("หยุดบันทึกไม่สำเร็จ ลองใหม่อีกครั้ง")); }
  if (r.guide) goGuide(r.guide, "edit"); else TICK();
}

// ---------------------------------------------------------------- record menu
async function onRecButton(e) {
  e.stopPropagation();
  closePopMenu();
  const b = e.currentTarget;
  if (STATUS && STATUS.recording) return busy(b, stopRecording);
  const m = document.getElementById("recmenu");
  if (!m.hidden) { m.hidden = true; return; }
  if (!STATUS) STATUS = await getJSON("/api/status");
  m.innerHTML = `<div class="pop-h">${tr("เลือกจอที่จะบันทึก")}</div><div class="mons"></div>
    <button class="btn dark full" id="startrec">${ICON.rec} ${tr("เริ่มบันทึก")}</button>
    <div class="muted small" style="margin-top:8px">${tr("หยุดได้ที่แผงมุมจอ หรือกด Ctrl+Alt+R")}</div>`;
  monitorList(m.querySelector(".mons"));
  m.querySelector("#startrec").onclick = ev => busy(ev.currentTarget, async () => {
    if (!(await postOk("/api/start"))) toastErr(tr("เริ่มบันทึกไม่สำเร็จ ลองใหม่อีกครั้ง"));
    m.hidden = true;
    TICK();
  });
  m.hidden = false;
  m.querySelector("#startrec").focus();
}

const lastFlash = {};
function hoverFlash(i) {
  const now = Date.now();
  if (now - (lastFlash[i] || 0) < 1500) return;
  lastFlash[i] = now;
  post("/api/flash?i=" + i);
}

// Monitor picker rows (record menu + settings); hover flashes, click selects.
function monitorList(box) {
  const st = STATUS;
  box.innerHTML = "";
  for (const mon of st.monitors) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "mon" + (mon.index === st.selected ? " on" : "");
    b.disabled = st.recording;
    b.innerHTML = `${ICON.monitor}<span>${tr("จอ {n}", {n: mon.index + 1})} · ${mon.w}×${mon.h}${mon.primary ? " · " + tr("จอหลัก") : ""}</span>` +
      `<span class="ck">${ICON.check}</span>`;
    b.onmouseenter = () => hoverFlash(mon.index);
    b.onclick = async e => {
      e.stopPropagation();
      lastFlash[mon.index] = Date.now();  // the select itself flashes
      await post("/api/monitor?i=" + mon.index);
      STATUS = await getJSON("/api/status");
      monitorList(box);
    };
    box.appendChild(b);
  }
}

// ---------------------------------------------------------------- guide lists
const appIcon = g => `<span class="appicon">${g.icon
  ? `<img src="${imgUrl(g.id, "app_icon.png")}" alt="">` : ICON.app}</span>`;

function viewToggle() {
  return `<div class="seg">` +
    `<button type="button" data-view="grid" class="${VIEW === "grid" ? "on" : ""}" title="${tr("การ์ด")}">${ICON.grid}</button>` +
    `<button type="button" data-view="list" class="${VIEW === "list" ? "on" : ""}" title="${tr("รายการ")}">${ICON.list}</button></div>`;
}
function bindViewToggle(root) {
  root.querySelectorAll("[data-view]").forEach(b => b.onclick = () => {
    if (VIEW === b.dataset.view) return;
    VIEW = b.dataset.view;
    post("/api/settings", {view: VIEW});
    refresh();
  });
}

function guideTools(el, g) {
  const t = el.querySelector(".ctools");
  t.innerHTML = `<button type="button" class="tool bm" title="${g.bookmarked ? tr("เลิกบุ๊กมาร์ก") : tr("บุ๊กมาร์ก")}">` +
    `${g.bookmarked ? ICON.bookmarkFill : ICON.bookmark}</button>` +
    `<button type="button" class="tool more" title="${tr("เพิ่มเติม")}">${ICON.more}</button>`;
  t.querySelector(".bm").setAttribute("aria-label", t.querySelector(".bm").title);
  t.querySelector(".more").setAttribute("aria-label", tr("เพิ่มเติม"));
  t.querySelector(".bm").onclick = e => {
    e.stopPropagation();
    busy(e.currentTarget, async () => {
      if (!(await postOk(`/api/guide/${encodeURIComponent(g.id)}/meta`, {bookmarked: !g.bookmarked})))
        toastErr(FAILED);
      refresh();
    });
  };
  t.querySelector(".more").onclick = e => {
    e.stopPropagation();
    const id = encodeURIComponent(g.id), anchor = e.currentTarget;
    const del = {label: tr("ลบ"), danger: true, run: async () => {
      if (await postOk(`/api/guide/${id}/delete`)) toast(tr("ย้ายไปถังขยะแล้ว")); else toastErr(FAILED);
      refresh();
    }};
    if (g.broken) return popMenu(anchor, [del]);
    popMenu(anchor, [
      {label: tr("เปิด"), run: () => goGuide(g.id, "view")},
      {label: tr("เปลี่ยนชื่อ"), run: async () => {
        const title = await uiPrompt(tr("เปลี่ยนชื่อคู่มือ"), g.title);
        if (title !== null && title.trim()) {
          if (await postOk(`/api/guide/${id}/meta`, {title})) toast(tr("เปลี่ยนชื่อแล้ว")); else toastErr(FAILED);
          refresh();
        }
      }},
      {label: tr("ทำสำเนา"), run: async () => {
        if (await postOk(`/api/guide/${id}/duplicate`)) toast(tr("ทำสำเนาแล้ว")); else toastErr(FAILED);
        refresh();
      }},
      {label: tr("ส่งออก"), run: () => exportMenu(anchor, g.id)},
      del,
    ]);
  };
}

function drawGuides(box, items, emptyText) {
  if (!items.length) { box.innerHTML = `<p class="empty">${esc(emptyText)}</p>`; return; }
  const wrap = document.createElement("div");
  wrap.className = VIEW === "grid" ? "cards" : "rows";
  for (const g of items) {
    const el = document.createElement("div");
    el.dataset.id = g.id;
    el.className = (VIEW === "grid" ? "card" : "row") + (g.bookmarked ? " marked" : "") + (g.broken ? " broken" : "");
    const info = g.broken ? `<span class="muted">${tr("ไฟล์เสียหาย เปิดไม่ได้")}</span>`
      : `${esc(g.ago)}<span class="dot">·</span>${tr("{n} ขั้นตอน", {n: g.count})}`;
    el.innerHTML = VIEW === "grid"
      ? `<div class="ctools"></div><div class="app">${appIcon(g)}<span>${esc(g.app)}</span></div>
         <div class="title">${esc(g.title)}</div>
         <div class="meta">${info}</div>`
      : `${appIcon(g)}<div class="r-title">${esc(g.title)}</div><div class="r-app">${esc(g.app)}</div>
         <div class="r-ago">${g.broken ? info : esc(g.ago)}</div>
         <div class="r-count">${g.broken ? "" : tr("{n} ขั้นตอน", {n: g.count})}</div><div class="ctools"></div>`;
    guideTools(el, g);
    activatable(el, () => g.broken
      ? toastErr(tr("ไฟล์ของคู่มือนี้เสียหาย เปิดไม่ได้ ดูไฟล์ guide.json ในโฟลเดอร์ {id} (ตั้งค่า > เปิดโฟลเดอร์) หรือลบทิ้งจากเมนู …",
        {id: g.id}), 9000)
      : goGuide(g.id, "view"), g.title);
    wrap.appendChild(el);
  }
  box.replaceChildren(wrap);
}

const EMPTY_ALL = tr("ยังไม่มีคู่มือ กด + บันทึกใหม่ เพื่อเริ่ม");
const FAILED = tr("ทำรายการไม่สำเร็จ ลองใหม่อีกครั้ง");

// What the app is for, said once on the home page (the first-time tour shows how).
const INTRO = `<p><b>StepCap</b> ${tr("บันทึกการคลิกและการพิมพ์ของคุณเป็นคู่มือทีละขั้นตอนพร้อมภาพ แล้วส่งออกเป็น Word, PDF, HTML หรือ Markdown ให้คนอื่นทำตามได้")}</p>`;

async function renderHome(c) {
  const my = ++RENDER;
  const [all, pages] = await Promise.all([getJSON("/api/guides"), getJSON("/api/pages")]);
  if (my !== RENDER) return;
  const recents = [...all].sort((a, b) => b.bookmarked - a.bookmarked).slice(0, 8);
  c.innerHTML = `<div class="intro">${INTRO}</div>
    <section><div class="sec-h"><h2>${tr("ล่าสุด")}</h2>${viewToggle()}</div><div id="recents"></div>
      ${all.length ? `<div class="center"><button type="button" class="btn" id="seeall">${tr("ดูทั้งหมด")}</button></div>` : ""}</section>
    <section><div class="sec-h"><h2>${tr("สถิติ")}</h2></div>
      <div class="stats"><div class="stat">${ICON.docs}<span>${tr("คู่มือทั้งหมด")}</span><b>${all.length}</b></div>
        <div class="stat">${ICON.page}<span>${tr("Page ทั้งหมด")}</span><b>${pages.length}</b></div></div></section>`;
  drawGuides(c.querySelector("#recents"), recents, EMPTY_ALL);
  bindViewToggle(c);
  c.querySelector("#seeall")?.addEventListener("click", () => go("all"));
  if (PAGE === "home") maybeTour("home");
}

async function renderAll(c) {
  const my = ++RENDER;
  const q = QTEXT.trim();
  const items = await getJSON(`/api/guides?q=${encodeURIComponent(q)}${BM_ONLY ? "&bookmarked=1" : ""}`);
  if (my !== RENDER) return;
  c.innerHTML = `<div class="sec-h"><h2>${tr("คู่มือทั้งหมด")}</h2>
      <label class="chk"><input type="checkbox" id="bmonly" ${BM_ONLY ? "checked" : ""}> ${tr("เฉพาะที่บุ๊กมาร์ก")}</label>
      ${viewToggle()}</div><div id="list"></div>`;
  const empty = q ? tr('ไม่พบคู่มือที่ตรงกับ "{q}"', {q}) : BM_ONLY ? tr("ยังไม่มีคู่มือที่บุ๊กมาร์ก") : EMPTY_ALL;
  drawGuides(c.querySelector("#list"), items, empty);
  bindViewToggle(c);
  c.querySelector("#bmonly").onchange = e => { BM_ONLY = e.target.checked; refresh(); };
}

async function renderTrash(c) {
  const my = ++RENDER;
  const items = await getJSON("/api/trash");
  if (my !== RENDER) return;
  c.innerHTML = `<div class="sec-h"><h2>${tr("ถังขยะ")}</h2>
      ${items.length ? `<button type="button" class="btn danger" id="empty">${tr("ล้างถังขยะ")}</button>` : ""}</div>
    <p class="muted">${tr("คู่มือในถังขยะไม่แสดงในหน้าอื่นและในผลค้นหา กู้คืนได้จนกว่าจะลบถาวร")}</p>
    ${items.length ? `<div class="rows">${items.map(t => `<div class="row static" data-id="${esc(t.id)}">
        <div class="r-title">${esc(t.title)}</div>
        <div class="r-ago">${t.ago ? tr("ลบเมื่อ {ago}", {ago: esc(t.ago)}) : ""}</div>
        <div class="r-count">${tr("{n} ขั้นตอน", {n: t.count})}</div>
        <div class="r-btns"><button type="button" class="btn" data-act="restore">${ICON.restore} ${tr("กู้คืน")}</button>
          <button type="button" class="btn danger" data-act="purge">${tr("ลบถาวร")}</button></div></div>`).join("")}</div>`
      : `<p class="empty">${tr("ถังขยะว่าง")}</p>`}`;
  c.querySelectorAll(".row").forEach(row => {
    const id = encodeURIComponent(row.dataset.id);
    row.querySelector('[data-act="restore"]').onclick = e => busy(e.currentTarget, async () => {
      if (await postOk(`/api/trash/${id}/restore`)) toast(tr("กู้คืนแล้ว"));
      else toastErr(tr("กู้คืนไม่ได้ อาจมีคู่มือรหัสเดียวกันอยู่แล้ว หรือไฟล์ถูกเปิดค้างอยู่"));
      refresh();
    });
    row.querySelector('[data-act="purge"]').onclick = e => busy(e.currentTarget, async () => {
      if (!await uiConfirm(tr("ลบถาวร? ไฟล์จะไปอยู่ในถังขยะของ Windows"), tr("ลบถาวร"))) return;
      if (await postOk(`/api/trash/${id}/purge`)) toast(tr("ลบถาวรแล้ว")); else toastErr(FAILED);
      refresh();
    });
  });
  c.querySelector("#empty")?.addEventListener("click", e => busy(e.currentTarget, async () => {
    if (!await uiConfirm(tr("ล้างถังขยะทั้งหมด {n} รายการ?", {n: items.length}), tr("ล้างถังขยะ"))) return;
    if (await postOk("/api/trash/empty")) toast(tr("ล้างถังขยะแล้ว")); else toastErr(FAILED);
    refresh();
  }));
}

async function renderSettings(c) {
  const my = ++RENDER;
  const s = await getJSON("/api/settings");
  if (!STATUS) STATUS = await getJSON("/api/status");
  if (my !== RENDER) return;
  c.innerHTML = `<div class="sec-h"><h2>${tr("ตั้งค่า")}</h2></div>
    <div class="set" id="setlang"><h3>${LANG_TITLE}</h3><div class="langs">${LANG_NAMES.map(([k, name]) =>
      `<label class="chk" for="lang-${k}"><input type="radio" name="lang" id="lang-${k}" value="${k}"${LANG === k ? " checked" : ""}>${name}</label>`).join("")}</div></div>
    <div class="set"><h3>${tr("จอเริ่มต้นสำหรับบันทึก")}</h3>
      <div class="muted">${tr("ใช้จอนี้ทุกครั้งที่กด + บันทึกใหม่ หรือปุ่มลัด")}</div><div class="mons" id="setmons"></div></div>
    <div class="set"><h3>${tr("ปุ่มลัด")}</h3>
      <div class="kv"><kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>R</kbd><span>${tr("เริ่ม/หยุดบันทึก")}</span></div>
      <div class="kv"><kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>P</kbd><span>${tr("พัก/ทำต่อ")}</span></div>
      <div class="muted">${tr("ยังเปลี่ยนปุ่มลัดไม่ได้")}</div></div>
    <div class="set"><h3>${tr("ที่เก็บคู่มือ")}</h3><div class="path">${esc(s.storage)}</div>
      <div class="muted small" style="margin-bottom:10px">${tr("โฟลเดอร์นี้มีภาพต้นฉบับก่อนเบลอด้วย ส่งต่อเฉพาะไฟล์ที่กดส่งออก อย่าส่งทั้งโฟลเดอร์")}</div>
      <button type="button" class="btn" id="openf">${ICON.folder} ${tr("เปิดโฟลเดอร์")}</button></div>
    <div class="set" id="setred"><h3>${tr("ซ่อนข้อมูลอัตโนมัติ")}</h3>
      <div class="muted">${tr("เบลอข้อมูลในภาพหลังบันทึกเสร็จ และในภาพที่เพิ่มทีหลัง อ่านได้เฉพาะตัวอักษรอังกฤษและตัวเลข ตรวจภาพอีกครั้งก่อนส่งให้คนอื่น")}</div>
      <div class="soon"><label class="swlabel"><span class="switch"><input type="checkbox" id="redon"
        ${s.redact_on && !s.redact_error ? "checked" : ""} ${s.redact_error ? "disabled" : ""}><span></span></span>
        <span>${s.redact_error ? tr("ใช้ไม่ได้บนเครื่องนี้: {err}", {err: esc(s.redact_error)}) : tr("เปิดใช้")}</span></label></div>
      <div class="redrules">${REDACT_RULES.map(([k, label]) => `<label class="chk">
        <input type="checkbox" data-rule="${k}" ${s.redact_rules.includes(k) ? "checked" : ""}> ${label}</label>`).join("")}</div>
      <div class="muted small">${tr("คำที่กำหนดเอง (บรรทัดละคำ)")}</div>
      <textarea id="redwords" class="dlg-in" rows="3" spellcheck="false">${esc(s.redact_custom.join("\n"))}</textarea></div>
    <div class="set"><h3>${tr("การแนะนำการใช้งาน")}</h3>
      <div class="muted">${tr("ดูคำแนะนำของปุ่มต่าง ๆ อีกครั้ง หรือเพิ่มคู่มือตัวอย่างกลับเข้ามาในคลัง")}</div>
      <div class="padd"><button type="button" class="btn" id="replaytour">${tr("แสดงคำแนะนำอีกครั้ง")}</button>
        <button type="button" class="btn" id="addsample">${tr("เพิ่มคู่มือตัวอย่างอีกครั้ง")}</button></div></div>`;
  monitorList(c.querySelector("#setmons"));
  c.querySelectorAll("[name=lang]").forEach(r => r.onchange = async () => {
    if (await postOk("/api/settings", {lang: r.value})) location.reload(); else toastErr(FAILED);
  });
  c.querySelector("#replaytour").onclick = e => busy(e.currentTarget, async () => {
    if (await postOk("/api/settings", {tours_seen: []})) go("home"); else toastErr(FAILED);
  });
  c.querySelector("#addsample").onclick = e => busy(e.currentTarget, async () => {
    try {
      const r = await post("/api/sample");
      if (r.ok) return nav({guide: (await r.json()).id, mode: "view", msg: "sample"});
    } catch { /* offline */ }
    toastErr(FAILED);
  });
  c.querySelector("#openf").onclick = async () => { if (!(await postOk("/api/open-folder"))) toastErr(FAILED); };
  const red = c.querySelector("#setred");
  // every change saves at once and says whether it stuck
  const save = async body => toast(...(await postOk("/api/settings", body)) ? [tr("บันทึกการตั้งค่าแล้ว"), 1500]
    : [tr("บันทึกการตั้งค่าไม่สำเร็จ"), 6000, "err"]);
  red.querySelector("#redon").onchange = e => save({redact_on: e.target.checked});
  red.querySelectorAll("[data-rule]").forEach(b => b.onchange = () => save(
    {redact_rules: [...red.querySelectorAll("[data-rule]:checked")].map(x => x.dataset.rule)}));
  red.querySelector("#redwords").onchange = e => save(
    {redact_custom: e.target.value.split("\n").map(w => w.trim()).filter(Boolean)});
}
const REDACT_RULES = [["email", tr("อีเมล")], ["phone", tr("เบอร์โทรศัพท์")], ["thai_id", tr("เลขบัตรประชาชน")],
  ["card", tr("เลขบัตรเครดิต/เดบิต")], ["bank", tr("เลขบัญชีธนาคาร")]];
// The one bilingual card, each language named in itself, so someone who
// can't read the current language still finds the way back.
const LANG_TITLE = "ภาษา / Language";  // i18n-ok
const LANG_NAMES = [["th", "ไทย"], ["en", "English"]];  // i18n-ok
