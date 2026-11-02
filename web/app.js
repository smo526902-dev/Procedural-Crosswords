"use strict";
// Procedural Crosswords - solver UI (no build step, no dependencies).

const $ = (s) => document.querySelector(s);
const NAMES = { 1: "Easy", 2: "Gentle", 3: "Medium", 4: "Hard", 5: "Expert" };
const AID_LABELS = {
  check: "Check", reveal_letter: "Reveal letter", reveal_word: "Reveal word", reveal_puzzle: "Reveal puzzle",
};

let P = null;          // puzzle JSON from the server
let N = 0;             // grid size
let cellEls = [];      // [r][c] -> element
let wordAt = [];       // [r][c] -> {A: idx, D: idx}
let S = null;          // solver state
let timerId = null;

// ------------------------------------------------------------------ storage
function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* private mode */ }
}
function recall(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (_) { return null; }
}

// ----------------------------------------------------------------- controls
function setupControls(meta) {
  const size = $("#size");
  for (const s of meta.sizes) size.add(new Option(`${s} × ${s}`, s));
  const boxes = $("#aid-boxes");
  for (const a of meta.aids) {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" name="aid" value="${a}" disabled> ${AID_LABELS[a]}`;
    boxes.append(l);
  }
  $("#aids-auto").addEventListener("change", (e) => {
    for (const b of document.querySelectorAll("input[name=aid]")) b.disabled = e.target.checked;
  });
  const lvl = $("#level");
  const show = () => ($("#level-name").textContent = NAMES[lvl.value]);
  lvl.addEventListener("input", show);
  show();
  $("#controls").addEventListener("submit", (e) => {
    e.preventDefault();
    newPuzzle(readControls());
  });
}

function readControls() {
  const req = { level: +$("#level").value };
  if ($("#size").value) req.size = +$("#size").value;
  if ($("#min-score").value) req.min_score = +$("#min-score").value;
  if ($("#clue-tier").value) req.clue_tier = +$("#clue-tier").value;
  if ($("#seed").value !== "") req.seed = +$("#seed").value;
  if (!$("#aids-auto").checked) {
    req.aids = [...document.querySelectorAll("input[name=aid]:checked")].map((b) => b.value);
  }
  return req;
}

function writeControls(req) {
  $("#level").value = req.level || 3;
  $("#level-name").textContent = NAMES[$("#level").value];
  $("#size").value = req.size || "";
  $("#min-score").value = req.min_score ?? "";
  $("#clue-tier").value = req.clue_tier || "";
  $("#seed").value = req.seed ?? "";
  const auto = !req.aids;
  $("#aids-auto").checked = auto;
  for (const b of document.querySelectorAll("input[name=aid]")) {
    b.disabled = auto;
    b.checked = !auto && req.aids.includes(b.value);
  }
}

function reqToHash(req) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(req)) {
    if (v === undefined || v === null) continue;
    q.set(k, Array.isArray(v) ? v.join(",") || "none" : v);
  }
  return q.toString();
}

function hashToReq() {
  const q = new URLSearchParams(location.hash.slice(1));
  if (!q.has("level")) return null;
  const req = { level: +q.get("level") };
  for (const k of ["seed", "size", "min_score", "clue_tier", "starter_letters"]) {
    if (q.has(k)) req[k] = +q.get(k);
  }
  if (q.has("aids")) req.aids = q.get("aids") === "none" ? [] : q.get("aids").split(",");
  return req;
}

// ------------------------------------------------------------------ loading
async function newPuzzle(req) {
  const status = $("#status");
  status.className = "status";
  status.textContent = "Generating puzzle…";
  $("#new").disabled = true;
  try {
    const res = await fetch("/api/puzzle", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : res.statusText);
    // Make the link reproducible: pin the seed that was actually used.
    const shared = { ...req, seed: data.seed };
    history.replaceState(null, "", "#" + reqToHash(shared));
    load(data, shared);
    status.textContent = "";
  } catch (err) {
    status.className = "status error";
    status.textContent = "Could not generate a puzzle: " + err.message;
  } finally {
    $("#new").disabled = false;
  }
}

function load(puzzle, req) {
  P = puzzle;
  N = P.size;
  P.req = req;
  wordAt = Array.from({ length: N }, () => Array.from({ length: N }, () => ({})));
  P.entries.forEach((e, i) => {
    for (let k = 0; k < e.length; k++) {
      const r = e.row + (e.direction === "D" ? k : 0);
      const c = e.col + (e.direction === "A" ? k : 0);
      wordAt[r][c][e.direction] = i;
    }
  });
  const saved = recall("xw:" + P.id);
  S = {
    letters: saved?.letters || P.grid.map((row) => [...row].map((ch) => (ch === "#" ? null : ""))),
    marks: saved?.marks || P.grid.map((row) => [...row].map(() => "")),
    elapsed: saved?.elapsed || 0,
    done: saved?.done || false,
    gaveUp: saved?.gaveUp || false,
    r: 0, c: 0, dir: "A",
  };
  for (const [r, c] of P.givens) {
    S.letters[r][c] = P.grid[r][c];
    S.marks[r][c] = "given";
  }
  const first = P.entries.find((e) => e.direction === "A");
  S.r = first.row; S.c = first.col;

  renderGrid();
  renderClues();
  renderMeta();
  setupAids();
  $("#app").hidden = false;
  select(S.r, S.c, "A");
  startTimer();
  $("#hidden-input").focus({ preventScroll: true });
}

// ---------------------------------------------------------------- rendering
function fitCells() {
  const avail = Math.min(window.innerWidth - 36, 620);
  const size = Math.max(22, Math.min(N <= 7 ? 60 : 44, Math.floor(avail / N) - 1));
  document.documentElement.style.setProperty("--cell-size", size + "px");
}

function renderGrid() {
  fitCells();
  const g = $("#grid");
  g.innerHTML = "";
  g.style.gridTemplateColumns = `repeat(${N}, var(--cell-size))`;
  const nums = {};
  for (const e of P.entries) nums[`${e.row},${e.col}`] = e.number;
  cellEls = [];
  for (let r = 0; r < N; r++) {
    cellEls.push([]);
    for (let c = 0; c < N; c++) {
      const d = document.createElement("div");
      d.className = "cell";
      if (P.grid[r][c] === "#") {
        d.classList.add("block");
      } else {
        const n = nums[`${r},${c}`];
        d.innerHTML = (n ? `<span class="num">${n}</span>` : "") + `<span class="ltr"></span>`;
        d.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          if (S.r === r && S.c === c) select(r, c, S.dir === "A" ? "D" : "A");
          else select(r, c, wordAt[r][c][S.dir] !== undefined ? S.dir : (S.dir === "A" ? "D" : "A"));
          $("#hidden-input").focus({ preventScroll: true });
        });
      }
      g.append(d);
      cellEls[r].push(d);
    }
  }
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) paintCell(r, c);
}

function paintCell(r, c) {
  if (P.grid[r][c] === "#") return;
  const d = cellEls[r][c];
  d.querySelector(".ltr").textContent = S.letters[r][c] || "";
  d.classList.remove("wrong", "revealed", "given", "correct");
  if (S.marks[r][c]) d.classList.add(S.marks[r][c]);
}

function renderClues() {
  for (const dir of ["A", "D"]) {
    const ol = $(dir === "A" ? "#across" : "#down");
    ol.innerHTML = "";
    P.entries.forEach((e, i) => {
      if (e.direction !== dir) return;
      const li = document.createElement("li");
      li.dataset.idx = i;
      li.innerHTML = `<b>${e.number}</b><span></span>`;
      li.querySelector("span").textContent = e.clue;
      li.addEventListener("click", () => {
        const k = firstEmpty(e);
        select(k.r, k.c, e.direction);
        $("#hidden-input").focus({ preventScroll: true });
      });
      ol.append(li);
    });
  }
}

function renderMeta() {
  const d = P.difficulty, q = P.quality;
  $("#meta").textContent =
    `${d.name} · ${N}×${N} · ${q.words} words · fill quality ${q.overall}/100 · seed ${P.seed}`;
  $("#dl-puz").href = `/api/puzzle/${P.id}/puz`;
  $("#dl-print").href = `/api/puzzle/${P.id}/print`;
}

function setupAids() {
  const aids = new Set(P.difficulty.aids);
  $("#check-menu").hidden = !aids.has("check");
  let anyReveal = false;
  for (const b of document.querySelectorAll("#reveal-menu button")) {
    b.hidden = !aids.has(b.dataset.aid);
    anyReveal ||= !b.hidden;
  }
  $("#reveal-menu").hidden = !anyReveal;
}

// ------------------------------------------------------------------ cursor
function cellsOf(e) {
  return Array.from({ length: e.length }, (_, k) => ({
    r: e.row + (e.direction === "D" ? k : 0), c: e.col + (e.direction === "A" ? k : 0),
  }));
}
function current() { return P.entries[wordAt[S.r][S.c][S.dir]]; }
function firstEmpty(e) { return cellsOf(e).find(({ r, c }) => !S.letters[r][c]) || cellsOf(e)[0]; }

function select(r, c, dir) {
  if (wordAt[r][c][dir] === undefined) dir = dir === "A" ? "D" : "A";
  S.r = r; S.c = c; S.dir = dir;
  highlight();
}

function highlight() {
  for (const row of cellEls) for (const d of row) d.classList.remove("in-word", "cursor");
  const e = current();
  for (const { r, c } of cellsOf(e)) cellEls[r][c].classList.add("in-word");
  cellEls[S.r][S.c].classList.add("cursor");
  $("#cur-label").textContent = `${e.number}${e.direction === "A" ? "A" : "D"}`;
  $("#cur-clue").textContent = e.clue;
  const idx = wordAt[S.r][S.c][S.dir];
  const crossIdx = wordAt[S.r][S.c][S.dir === "A" ? "D" : "A"];
  for (const li of document.querySelectorAll(".clues li")) {
    const i = +li.dataset.idx;
    li.classList.toggle("active", i === idx);
    li.classList.toggle("cross", i === crossIdx);
    li.classList.toggle("filled", cellsOf(P.entries[i]).every(({ r, c }) => S.letters[r][c]));
    if (i === idx || i === crossIdx) scrollClue(li);
  }
}

// Keep the active clue visible inside its own column, without ever scrolling
// the page itself (on phones the lists sit below the grid).
function scrollClue(li) {
  const box = li.closest(".clues > div");
  if (!box || box.scrollHeight <= box.clientHeight) return;
  const top = li.offsetTop - box.offsetTop;
  if (top < box.scrollTop) box.scrollTop = top - 8;
  else if (top + li.offsetHeight > box.scrollTop + box.clientHeight) {
    box.scrollTop = top + li.offsetHeight - box.clientHeight + 8;
  }
}

function locked(r, c) {
  return S.done || S.marks[r][c] === "given" || S.marks[r][c] === "revealed" || S.marks[r][c] === "correct";
}

function typeLetter(ch) {
  if (S.done) return;
  const { r, c } = S;
  if (!locked(r, c)) {
    S.letters[r][c] = ch;
    S.marks[r][c] = "";
    paintCell(r, c);
  }
  // advance to the next empty cell in the word, else the next cell
  const cells = cellsOf(current());
  const at = cells.findIndex((p) => p.r === r && p.c === c);
  const next = cells.slice(at + 1).find((p) => !S.letters[p.r][p.c]) || cells[at + 1];
  if (next) select(next.r, next.c, S.dir);
  else if (cells.every((p) => S.letters[p.r][p.c])) jumpWord(1, true);
  else highlight();
  afterChange();
}

function backspace() {
  if (S.done) return;
  const { r, c } = S;
  if (S.letters[r][c] && !locked(r, c)) {
    S.letters[r][c] = "";
    S.marks[r][c] = "";
    paintCell(r, c);
  } else {
    const cells = cellsOf(current());
    const at = cells.findIndex((p) => p.r === r && p.c === c);
    const prev = cells[at - 1];
    if (prev) {
      if (!locked(prev.r, prev.c)) { S.letters[prev.r][prev.c] = ""; S.marks[prev.r][prev.c] = ""; paintCell(prev.r, prev.c); }
      select(prev.r, prev.c, S.dir);
    }
  }
  highlight();
  afterChange();
}

function move(dr, dc) {
  const dir = dr ? "D" : "A";
  if (S.dir !== dir) { select(S.r, S.c, dir); return; }
  let r = S.r + dr, c = S.c + dc;
  while (r >= 0 && r < N && c >= 0 && c < N && P.grid[r][c] === "#") { r += dr; c += dc; }
  if (r >= 0 && r < N && c >= 0 && c < N) select(r, c, S.dir);
}

function jumpWord(delta, skipFilled = false) {
  const order = P.entries.map((e, i) => i);
  order.sort((a, b) => (P.entries[a].direction === P.entries[b].direction
    ? P.entries[a].number - P.entries[b].number
    : P.entries[a].direction === "A" ? -1 : 1));
  let pos = order.indexOf(wordAt[S.r][S.c][S.dir]);
  for (let tries = 0; tries < order.length; tries++) {
    pos = (pos + delta + order.length) % order.length;
    const e = P.entries[order[pos]];
    if (!skipFilled || cellsOf(e).some(({ r, c }) => !S.letters[r][c])) {
      const k = firstEmpty(e);
      select(k.r, k.c, e.direction);
      return;
    }
  }
  highlight();
}

// --------------------------------------------------------------- aids
function scopeCells(scope) {
  if (scope === "letter") return [{ r: S.r, c: S.c }];
  if (scope === "word") return cellsOf(current());
  const all = [];
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) if (P.grid[r][c] !== "#") all.push({ r, c });
  return all;
}

function check(scope) {
  for (const { r, c } of scopeCells(scope)) {
    if (!S.letters[r][c] || locked(r, c)) continue;
    S.marks[r][c] = S.letters[r][c] === P.grid[r][c] ? "correct" : "wrong";
    paintCell(r, c);
  }
  afterChange();
}

function reveal(scope) {
  for (const { r, c } of scopeCells(scope)) {
    if (S.letters[r][c] === P.grid[r][c] && S.marks[r][c] !== "wrong") continue;
    S.letters[r][c] = P.grid[r][c];
    S.marks[r][c] = "revealed";
    paintCell(r, c);
  }
  highlight();
  afterChange();
}

function clearAll() {
  if (S.done) return;
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
    if (P.grid[r][c] === "#" || S.marks[r][c] === "given") continue;
    S.letters[r][c] = ""; S.marks[r][c] = ""; paintCell(r, c);
  }
  highlight();
  afterChange();
}

function giveUp() {
  if (S.done) return;
  S.gaveUp = true;
  reveal("puzzle");
}

// ------------------------------------------------------------- completion
function afterChange() {
  let full = true, right = true;
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
    if (P.grid[r][c] === "#") continue;
    if (!S.letters[r][c]) full = false;
    else if (S.letters[r][c] !== P.grid[r][c]) right = false;
  }
  if (full && right && !S.done) {
    S.done = true;
    stopTimer();
    const revealed = S.marks.flat().filter((m) => m === "revealed").length;
    $("#done-title").textContent = S.gaveUp ? "Answers revealed" : "Solved!";
    $("#done-text").textContent = S.gaveUp
      ? "Here's the full solution. Try another?"
      : `${P.difficulty.name} ${N}×${N} in ${fmt(S.elapsed)}` +
        (revealed ? ` with ${revealed} revealed letter${revealed > 1 ? "s" : ""}.` : ", no help needed!");
    $("#done").showModal();
  } else if (full && !right && !S.done) {
    $("#status").textContent = "The grid is full, but something isn't right yet.";
  } else {
    $("#status").textContent = "";
  }
  store("xw:" + P.id, { letters: S.letters, marks: S.marks, elapsed: S.elapsed, done: S.done, gaveUp: S.gaveUp });
}

// ------------------------------------------------------------------ timer
function fmt(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
function startTimer() {
  stopTimer();
  $("#timer").textContent = fmt(S.elapsed);
  if (S.done) return;
  timerId = setInterval(() => {
    if (document.hidden) return;
    S.elapsed += 1;
    $("#timer").textContent = fmt(S.elapsed);
    if (S.elapsed % 10 === 0) store("xw:" + P.id, { letters: S.letters, marks: S.marks, elapsed: S.elapsed, done: S.done, gaveUp: S.gaveUp });
  }, 1000);
}
function stopTimer() { if (timerId) clearInterval(timerId); timerId = null; }

// ------------------------------------------------------------------ input
function onKey(e) {
  if (!P || e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key;
  if (/^[a-zA-Z]$/.test(k)) { e.preventDefault(); typeLetter(k.toUpperCase()); }
  else if (k === "Backspace" || k === "Delete") { e.preventDefault(); backspace(); }
  else if (k === "ArrowLeft") { e.preventDefault(); move(0, -1); }
  else if (k === "ArrowRight") { e.preventDefault(); move(0, 1); }
  else if (k === "ArrowUp") { e.preventDefault(); move(-1, 0); }
  else if (k === "ArrowDown") { e.preventDefault(); move(1, 0); }
  else if (k === "Tab") { e.preventDefault(); jumpWord(e.shiftKey ? -1 : 1); }
  else if (k === " " || k === "Enter") { e.preventDefault(); select(S.r, S.c, S.dir === "A" ? "D" : "A"); }
}

function setupInput() {
  const hi = $("#hidden-input");
  hi.addEventListener("keydown", onKey);
  // Mobile keyboards often send "Unidentified" keydowns; read the text instead.
  hi.addEventListener("input", () => {
    const v = hi.value.replace(/[^a-z]/gi, "");
    hi.value = "";
    for (const ch of v) typeLetter(ch.toUpperCase());
  });
  document.addEventListener("keydown", (e) => {
    if (document.activeElement === hi || !P || $("#done").open) return;
    const t = document.activeElement?.tagName;
    if (t === "INPUT" || t === "SELECT" || t === "TEXTAREA" || t === "BUTTON" || t === "SUMMARY") return;
    onKey(e);
  });
  document.querySelector(".toolbar").addEventListener("click", (e) => {
    const act = e.target.dataset?.act;
    if (!act || !P) return;
    const [verb, scope] = act.split("-");
    if (verb === "check") check(scope);
    else if (verb === "reveal") reveal(scope);
    else if (act === "clear") clearAll();
    else if (act === "give-up") giveUp();
    $("#hidden-input").focus({ preventScroll: true });
  });
  $("#share").addEventListener("click", async (e) => {
    e.preventDefault();
    try { await navigator.clipboard.writeText(location.href); $("#share").textContent = "Link copied"; }
    catch (_) { $("#share").textContent = "Copy the address bar"; }
    setTimeout(() => ($("#share").textContent = "Copy share link"), 1800);
  });
  window.addEventListener("resize", () => { if (P) fitCells(); });
}

// ------------------------------------------------------------------- boot
(async function boot() {
  let meta = { sizes: [5, 7, 9, 11, 13, 15], aids: Object.keys(AID_LABELS) };
  try { meta = await (await fetch("/api/presets")).json(); } catch (_) { /* use defaults */ }
  setupControls(meta);
  setupInput();
  const fromHash = hashToReq();
  const req = fromHash || { level: 3 };
  writeControls(req);
  $("#seed").value = ""; // a shared link pins its seed; "New puzzle" should still be fresh
  newPuzzle(req);
})();
