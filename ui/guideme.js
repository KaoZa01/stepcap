// Guide Me side panel (its own frameless window, docked at the screen's right
// edge): every step as a card, the current one open with its picture. The app
// finds the target on screen and moves on when it is clicked; this page only
// shows where things are and sends back / next / jump / close.
"use strict";
const GM = {gid: null, g: null, key: "", idx: -1, imgs: {}};

async function guideMePage(gid) {
  GM.gid = gid;
  document.title = "StepCap - " + tr("พาทำ");
  try {
    const r = await api("/api/guide/" + encodeURIComponent(gid));
    if (!r.ok) throw new Error(r.status);
    GM.g = await r.json();
  } catch {
    app.innerHTML = `<p class="muted gm-empty">${tr("เปิดคู่มือนี้ไม่ได้")}</p>`;
    return;
  }
  app.innerHTML = `<div class="gm">
    <header class="gm-top"><div class="gm-title">${esc(GM.g.title)}</div>
      <button type="button" class="icon-btn" id="gm-close" title="${tr("ปิดพาทำ")}" aria-label="${tr("ปิดพาทำ")}">${ICON.x}</button></header>
    <ol class="gm-list" id="gm-list"></ol>
    <footer class="gm-foot">
      <button type="button" class="btn" id="gm-back">${ICON.back} ${tr("ย้อนกลับ")}</button>
      <button type="button" class="btn dark" id="gm-next">${tr("ถัดไป")} ${ICON.fwd}</button></footer></div>`;
  const go = body => post("/api/guideme/go", body).catch(() => {});
  const close = () => post("/api/guideme/stop").catch(() => {});
  document.getElementById("gm-close").onclick = close;
  document.getElementById("gm-back").onclick = () => go({step: "back"});
  document.getElementById("gm-next").onclick = () => go({step: "next"});
  document.getElementById("gm-list").onclick = e => {
    if (e.target.closest("#gm-finish")) return close();
    const card = e.target.closest(".gm-card[data-i]");
    if (card && !card.classList.contains("on")) go({to: +card.dataset.i});
  };
  document.addEventListener("keydown", e => { if (e.code === "Escape") close(); });
  gmPoll();
}

async function gmPoll() {
  let s = {index: 0, done: false, state: "none", app: ""};  // not running (e.g. a test): first step
  try {
    const r = await (await api("/api/guideme")).json();
    if (r.active && r.gid === GM.gid) s = r;
  } catch { /* the app is closing */ }
  gmRender(s);
  setTimeout(gmPoll, 500);
}

function gmRender(s) {
  const key = [s.index, s.done, s.state, s.app].join("|");
  if (key === GM.key) return;
  GM.key = key;
  const steps = GM.g.steps;
  let n = 0;
  const cards = steps.map((st, i) => {
    const num = st.kind === "note" ? "•" : ++n;
    const on = !s.done && i === s.index;
    let body = "";
    if (on) {
      const status = s.state === "approx" ? tr("ตำแหน่งโดยประมาณ")
        : s.state === "missing" ? tr("หาเป้าหมายไม่เจอ เปิด {app} ให้ตรงกับหน้านี้ก่อน", {app: s.app}) : "";
      body = (status ? `<p class="gm-status${s.state === "missing" ? " warn" : ""}">${esc(status)}</p>` : "")
        + (st.image ? `<canvas class="gm-img"></canvas>` : "");
    }
    return `<li class="gm-card${on ? " on" : ""}" data-i="${i}"><div class="gm-head">
      <span class="gm-num">${num}</span><span class="gm-text">${esc(st.text || "")}</span></div>${body}</li>`;
  });
  if (s.done) cards.push(`<li class="gm-card on gm-done"><div class="gm-head"><span class="gm-num">${ICON.check}</span>
    <span class="gm-text">${tr("เสร็จแล้ว")}</span></div>
    <button type="button" class="btn dark" id="gm-finish">${tr("ปิด")}</button></li>`);
  const list = document.getElementById("gm-list");
  list.innerHTML = cards.join("");
  document.getElementById("gm-back").disabled = s.index === 0;
  document.getElementById("gm-next").disabled = s.done;
  const cur = list.querySelector(".gm-card.on");
  const st = steps[s.index];
  const cv = cur && cur.querySelector(".gm-img");
  if (cv) gmImage(st.image).then(img => img && drawStepCanvas(cv, img, st, 640));
  if (cur && s.index !== GM.idx) cur.scrollIntoView({block: "nearest"});
  GM.idx = s.index;
}

function gmImage(file) {
  if (!GM.imgs[file]) GM.imgs[file] = new Promise(res => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => res(null);
    img.src = imgUrl(GM.gid, file);
  });
  return GM.imgs[file];
}
