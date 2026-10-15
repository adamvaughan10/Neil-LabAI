/* LoopVLA Lab mode: Live loop, Runs, Labels, Models. Plain JS, no build step.
   Shares the demo counter and the overnight upgrade with app.js through window.LOOP. */
(() => {
  const L = window.LAB_DATA, P = window.LOOP;
  if (!L || !P) return;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(d));
  const pad = (n, w) => String(n).padStart(w, "0");
  const median = a => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };
  const quant = (a, q) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(q * (s.length - 1)))]; };
  const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
                  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };
  const CH = [["Left wheel", "--s-left"], ["Right wheel", "--s-right"], ["Arm", "--s-arm"], ["Gripper", "--s-grip"]];
  const CLOSED = -45, LIFTED = -15;
  const RUNS = L.rollouts.filter(r => r.steps);
  const DEMOS = P.EPS.slice(0, 97);
  const tOf = l => { const m = /session_\d{8}_(\d{2})(\d{2})/.exec(l.name); return m ? `${m[1]}:${m[2]}` : ""; };
  const hhmmss = id => { const t = id.slice(-6); return `${t.slice(0, 2)}:${t.slice(2, 4)}:${t.slice(4)}`; };

  // ---------- Shared: production model ----------
  const MODELS = [
    { v: "Base", name: "lerobot/smolvla_base", job: "—", mode: "not trained on Neil", trained: "SO-100 arms, not Neil", rate: 0, n: "", real: false },
    { v: "v1", name: "pick_cup", job: "181436", mode: "target angles", trained: "50 demos · 10,000 steps", rate: 0.4, n: "", real: false },
    { v: "v2", name: "handoff_pick_cup_pos2", job: "—", mode: "delta: wheel degrees still to turn", trained: "pick_cup + handoff demos", rate: 0.6, n: "3 of 5 runs, 15 Oct", real: true },
    { v: "v3", name: "pick_cup_angle_182076", job: "182076", mode: "angle: wheel target angles", trained: "pick_cup, angle actions", rate: null, n: "", real: false },
  ];
  let prod = "v2";
  const syncV3 = () => { if (P.S.version >= 4 && MODELS[3].rate == null) { MODELS[3].rate = 0.81; MODELS[3].n = "after tonight's training"; } };

  // ---------- Chart helper (canvas, theme colours) ----------
  function chart(cv, { h, xMax, lines, vlines = [], playhead = null, zero = true, labels = true }) {
    const dpr = devicePixelRatio || 1, w = cv.clientWidth;
    if (!w) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = w * dpr; cv.height = h * dpr; }
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    let lo = Infinity, hi = -Infinity;
    lines.forEach(l => l.pts.forEach(([, y]) => { if (y == null) return; if (y < lo) lo = y; if (y > hi) hi = y; }));
    if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (!(hi - lo > 1e-6)) { hi = (hi === -Infinity ? 1 : hi + 1); lo = (lo === Infinity ? -1 : lo - 1); }
    const m = (hi - lo) * 0.1; lo -= m; hi += m;
    const X = x => 4 + (x / xMax) * (w - 8), Y = y => 5 + (1 - (y - lo) / (hi - lo)) * (h - 10);
    g.strokeStyle = "rgba(27,42,89,.12)"; g.lineWidth = 1;
    vlines.forEach(x => { g.beginPath(); g.moveTo(X(x) + .5, 0); g.lineTo(X(x) + .5, h); g.stroke(); });
    if (zero) { g.strokeStyle = "rgba(27,42,89,.25)"; g.beginPath(); g.moveTo(0, Y(0)); g.lineTo(w, Y(0)); g.stroke(); }
    for (const l of lines) {
      g.strokeStyle = l.color; g.lineWidth = l.width || 2; g.globalAlpha = l.alpha ?? 1; g.setLineDash(l.dash || []); g.lineJoin = "round";
      g.beginPath(); let on = false;
      l.pts.forEach(([x, y]) => { if (y == null) { on = false; return; } on ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)); on = true; });
      g.stroke();
    }
    g.setLineDash([]); g.globalAlpha = 1;
    if (playhead != null) { g.strokeStyle = css("--navy"); g.globalAlpha = .55; g.lineWidth = 1.5; g.beginPath(); g.moveTo(X(playhead), 0); g.lineTo(X(playhead), h); g.stroke(); g.globalAlpha = 1; }
    if (labels) { g.fillStyle = css("--navy-2"); g.font = "700 10px " + css("--mono"); g.fillText(fmt(hi, 0), 7, 13); g.fillText(fmt(lo, 0), 7, h - 5); }
  }
  const idxAt = (rows, t) => { let a = 0, b = rows.length - 1; while (a < b) { const m = (a + b + 1) >> 1; rows[m][0] <= t ? (a = m) : (b = m - 1); } return a; };

  // ---------- Metrics ----------
  function rMetrics(r) {
    const f = r.full, T = f[f.length - 1][0], dts = f.slice(1).map((row, i) => (row[0] - f[i][0]) * 1000);
    let closeT = null, liftT = null;
    for (const row of f) { if (closeT == null && row[12] <= CLOSED) closeT = row[0]; if (closeT != null && liftT == null && row[11] <= LIFTED) liftT = row[0]; }
    const maxI = dts.indexOf(Math.max(...dts));
    return { T, n: f.length, hz: (f.length - 1) / T, med: quant(dts, .5), p95: quant(dts, .95), max: dts[maxI], maxAt: f[maxI][0], maxStep: maxI + 1, dts,
      chunks: f.reduce((a, row) => a + row[13], 0), closeT, liftT, wheel: [f[f.length - 1][14], f[f.length - 1][15]], final: f[f.length - 1].slice(9, 13) };
  }
  function dSeries(e) {   // her motor log is 48 points across the demo
    const n = e.sig.grip.length;
    return e.sig.grip.map((_, i) => [(i / (n - 1)) * e.dur, e.sig.left[i], e.sig.right[i], e.sig.arm[i], e.sig.grip[i]]);
  }
  function dMetrics(e) {
    const s = dSeries(e);
    let open = false, closeT = null, liftT = null;
    for (const row of s) {
      if (row[4] != null && row[4] > -35) open = true;
      if (open && closeT == null && row[4] != null && row[4] <= CLOSED) closeT = row[0];
      if (closeT != null && liftT == null && row[3] != null && row[3] <= LIFTED) liftT = row[0];
    }
    return { closeT, liftT };
  }
  RUNS.forEach(r => { r.m = rMetrics(r); });

  // ================= LIVE LOOP =================
  const ov = { f: $("#ov-front"), t: $("#ov-top") };
  const O = { runNo: 1, idx: 0, runs: 7, ok: 3, miss: 2, stop: 2, judged: 50, pool: L.labels.filter(l => !l.demo || !DEMOS.some(d => d.id === l.demo)).concat(L.labels), pi: 0, ending: false };
  const oRanges = (() => {
    const w = RUNS.flatMap(r => r.full.flatMap(s => [s[5], s[6]])), a = RUNS.flatMap(r => r.full.flatMap(s => [s[11], s[12]]));
    return { w: [Math.min(...w), Math.max(...w)], a: [Math.min(...a), Math.max(...a)] };
  })();
  $("#o-chans").innerHTML = [["Wheels", "speed sent", "--s-left"], ["Arm + gripper", "angle measured", "--s-grip"]].map(([n, u], i) =>
    `<div class="chan"><span class="nm">${n}<small>${u}</small></span><canvas id="oc-${i}" height="64"></canvas><div class="vals" id="ocv-${i}"></div></div>`).join("");
  function oLoad(i) {
    O.idx = i % RUNS.length; const r = RUNS[O.idx];
    O.ending = false; $("#o-verdict").classList.remove("on");
    ov.f.src = `assets/lab/${r.id}/front.mp4`; ov.t.src = `assets/lab/${r.id}/top.mp4`;
    $("#o-run").textContent = "Rollout " + O.runNo;
    $("#o-meta").textContent = `replaying the run from ${hhmmss(r.id)}, 15 Oct`;
    if ($("#v-ops").classList.contains("on")) { ov.f.play().catch(() => {}); ov.t.play().catch(() => {}); }
  }
  function oFrame() {
    if (!$("#v-ops").classList.contains("on")) return;
    const r = RUNS[O.idx], f = r.full, T = r.m.T, t = ov.f.duration ? (ov.f.currentTime / ov.f.duration) * T : 0, k = idxAt(f, t), row = f[k];
    chart($("#oc-0"), { h: 64, xMax: T, playhead: row[0], lines: [
      { pts: f.map(x => [x[0], x[5]]), color: css("--s-left"), alpha: .25 }, { pts: f.slice(0, k + 1).map(x => [x[0], x[5]]), color: css("--s-left") },
      { pts: f.map(x => [x[0], x[6]]), color: css("--s-right"), alpha: .25 }, { pts: f.slice(0, k + 1).map(x => [x[0], x[6]]), color: css("--s-right") }] });
    chart($("#oc-1"), { h: 64, xMax: T, playhead: row[0], lines: [
      { pts: f.map(x => [x[0], x[11]]), color: css("--s-arm"), alpha: .25 }, { pts: f.slice(0, k + 1).map(x => [x[0], x[11]]), color: css("--s-arm") },
      { pts: f.map(x => [x[0], x[12]]), color: css("--s-grip"), alpha: .25 }, { pts: f.slice(0, k + 1).map(x => [x[0], x[12]]), color: css("--s-grip") }] });
    $("#ocv-0").innerHTML = `<span>left <b>${fmt(row[5])}</b></span><span>right <b>${fmt(row[6])}</b></span>`;
    $("#ocv-1").innerHTML = `<span>arm <b>${row[11]}°</b></span><span>gripper <b>${row[12]}°</b></span>`;
    $("#o-run-sub").textContent = `Model ${prod} on Neil · ${fmt(ov.f.currentTime || 0)} s of ${fmt(T, 0)} s`;
    $("#o-now").innerHTML = [["step", `${k + 1} / ${f.length}`], ["action chunk", `#${f.slice(0, k + 1).reduce((a, x) => a + x[13], 0)}`],
      ["gripper", row[12] <= CLOSED ? "closed" : "open"], ["arm", row[11] <= LIFTED ? "raised" : "lowered"]].map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join("");
    if (Math.abs(ov.t.currentTime - ov.f.currentTime) > .3 && !ov.f.paused) ov.t.currentTime = ov.f.currentTime;
  }
  ov.f.addEventListener("ended", () => {
    if (O.ending) return; O.ending = true;
    const r = RUNS[O.idx], ok = r.outcome === "grasped";
    O.runs++; ok ? O.ok++ : O.miss++;
    $("#o-verdict").innerHTML = `<div style="display:flex;gap:8px;align-items:center">${ok ? '<span class="pill2 ok">Grasped</span>' : '<span class="pill2 bad">Missed</span>'}<span>Run complete</span></div>
      <span class="muted">${esc(r.note)}</span><span style="color:var(--pink-text)">Recorded · sent to Claude for a verdict</span>`;
    $("#o-verdict").classList.add("on");
    P.S.demos++; P.refresh();
    if (P.S.demos >= P.S.goal && P.S.version < 4 && !P.S.storyOn) P.upgrade();
    $("#o-last").textContent = `Last: rollout ${O.runNo} · ${ok ? "grasped" : "missed"}`;
    $("#o-record").classList.add("hot"); setTimeout(() => $("#o-record").classList.remove("hot"), 2200);
    setTimeout(() => { O.runNo++; oLoad(O.idx + 1); }, 3200);
  });
  function oFeedAdd(l, judging) {
    const el = document.createElement("div"); el.className = "fitem";
    const fill = j => {
      el.innerHTML = `<div class="row">${j ? '<span class="pill2 lab"><span class="dot"></span>Judging</span>' : l.success ? '<span class="pill2 ok">Picked up</span>' : '<span class="pill2 bad">Missed</span>'}
        <span>${l.spot ? "Spot " + l.spot : esc(l.group)}</span><span class="t">${tOf(l)}</span>${j ? "" : `<span class="c">${Math.round(l.confidence * 100)}% sure</span>`}</div>
        <div class="why">${j ? "Watching 8 frames from each camera…" : esc(l.reason)}</div>`;
    };
    fill(judging); $("#o-feed").prepend(el);
    while ($("#o-feed").children.length > 8) $("#o-feed").lastChild.remove();
    return { el, fill };
  }
  L.labels.filter(l => l.demo && DEMOS.some(d => d.id === l.demo)).slice(-5).forEach(l => oFeedAdd(l, false).el.style.animation = "none");
  function oJudge() {
    if (O.judged >= P.S.demos) return;
    const l = O.pool[O.pi++ % O.pool.length], it = oFeedAdd(l, true);
    $("#o-label").classList.add("hot");
    setTimeout(() => { it.fill(false); O.judged++; $("#o-label").classList.remove("hot"); oRender(); }, 1800);
  }
  function oRender() {
    const S = P.S; syncV3();
    $("#o-demos").textContent = S.demos;
    $("#o-today").textContent = `Since 09:47: ${O.runs} runs · ${O.ok} grasped · ${O.miss} missed · ${O.stop} stopped`;
    $("#o-judged").textContent = O.judged; $("#o-total").textContent = S.demos; $("#o-queue").textContent = Math.max(0, S.demos - O.judged);
    $("#o-label-bar").style.width = (100 * O.judged / S.demos) + "%";
    const tl = $("#tLbl")?.textContent, training = tl === "Training now";
    $("#o-train").classList.toggle("hot", training);
    if (training) {
      $("#o-train-pill").className = "pill2 ai"; $("#o-train-pill").innerHTML = '<span class="dot"></span>Training v3';
      $("#o-train-n").innerHTML = `${$("#tVal").textContent}`; $("#o-train-bar").style.width = $("#tBar").style.width;
      $("#o-train-sub").textContent = "SmolVLA on Athena · started by itself";
    } else {
      $("#o-train-pill").className = "pill2 " + (S.version >= 4 ? "ok" : "wait"); $("#o-train-pill").textContent = S.version >= 4 ? "v3 trained" : "Collecting";
      $("#o-train-n").innerHTML = `${S.demos} <small>/ ${S.goal} demos</small>`; $("#o-train-bar").style.width = Math.min(100, 100 * S.demos / S.goal) + "%";
      $("#o-train-sub").textContent = S.version >= 4 ? `v3 ready: 81% in tonight's test (demo value) · next at ${S.goal}` : `Trains on Athena by itself at ${S.goal} good demos`;
    }
    const sum = L.summary;
    $("#o-rate").textContent = `${Math.round(100 * sum.successes / sum.attempts)}% picked up · ${sum.successes} / ${sum.attempts} real verdicts`;
  }
  let oNext = 0;
  setInterval(() => { if (performance.now() > oNext) { oNext = performance.now() + 6000; oJudge(); } oRender(); }, 500);

  // ================= RUNS =================
  const ITEMS = [
    ...L.rollouts.map(r => ({ key: r.id, kind: "r", r, title: "Rollout " + hhmmss(r.id), disabled: !r.steps,
      sub: r.steps ? `v2 · ${fmt(r.duration_s)} s · ${r.steps} steps · 15 Oct` : "stopped before the first step", outcome: r.outcome })),
    ...DEMOS.map(e => ({ key: e.id, kind: "d", e, title: `Demo ${e.no}`, sub: `spot ${e.pos} · ${fmt(e.dur)} s · ${e.steps} steps · ${e.time}`,
      outcome: e.v ? (e.v.success ? "picked" : "missed") : "unjudged" })),
  ];
  let cur = null, rf = "all", dk = 0, dTimer = null;
  const chip = o => ({ grasped: '<span class="pill2 ok">Grasped</span>', missed_cup: '<span class="pill2 bad">Missed</span>', aborted: '<span class="pill2 wait">Stopped</span>',
    picked: '<span class="pill2 ok">Picked up</span>', missed: '<span class="pill2 bad">Missed</span>', unjudged: '<span class="pill2 wait">Not judged</span>' }[o]);
  function rList() {
    $("#rlist").innerHTML = ITEMS.filter(i => rf === "all" || i.kind === rf).map(i =>
      `<button class="ritem" data-key="${i.key}" ${i.disabled ? "disabled" : ""} aria-current="${cur?.key === i.key}"><span class="t1">${chip(i.outcome)}${esc(i.title)}</span><span class="t2">${esc(i.sub)}</span></button>`).join("");
    $$("#rlist .ritem").forEach(b => b.onclick = () => rSelect(b.dataset.key));
  }
  $$("#rf .chip").forEach(c => c.onclick = () => { rf = c.dataset.rf; $$("#rf .chip").forEach(x => x.classList.toggle("on", x === c)); rList(); });
  const rv = () => ({ f: $("#rv-front"), t: $("#rv-top") });
  function rSelect(key) {
    cur = ITEMS.find(i => i.key === key); if (!cur || cur.disabled) return;
    clearInterval(dTimer); dk = 0;
    const r = cur.kind === "r";
    $("#r-title").textContent = cur.title;
    $("#r-chips").innerHTML = chip(cur.outcome) + (r ? `<span class="pill2 wait">${esc(cur.r.model)}</span><span class="pill2 wait">${esc(cur.r.config.action_mode)} actions</span>`
      : `<span class="pill2 wait">teleoperated · spot ${cur.e.pos}</span><span class="pill2 wait">${esc(cur.e.batch)}</span>`);
    $("#r-cams").innerHTML = r
      ? `<div class="cam"><video id="rv-front" muted playsinline preload="auto" src="assets/lab/${cur.r.id}/front.mp4"></video><span class="lbl">Neil's eye</span></div>
         <div class="cam wide" style="align-self:start"><video id="rv-top" muted playsinline preload="auto" src="assets/lab/${cur.r.id}/top.mp4"></video><span class="lbl">Top camera</span></div>`
      : `<div class="cam"><img id="rd-front" alt="Neil's eye"><span class="lbl">Neil's eye</span></div>
         <div class="cam wide" style="align-self:start"><img id="rd-top" alt="Top camera"><span class="lbl">Top camera</span></div>`;
    $("#r-strip").hidden = r;
    if (!r) {
      $("#r-strip").innerHTML = Array.from({ length: 10 }, (_, k) => `<img data-k="${k}" src="assets/eps/${cur.e.id}/t${pad(k, 2)}.jpg" alt="frame ${k + 1}">`).join("");
      $$("#r-strip img").forEach(im => im.onclick = () => { dStop(); dShow(+im.dataset.k); });
      dShow(0);
    } else {
      const v = rv(); v.f.playbackRate = v.t.playbackRate = +$("#r-rate").value;
      v.f.addEventListener("ended", () => { $("#r-play").textContent = "Play"; });
    }
    $("#r-play").textContent = "Play";
    $("#r-chans").innerHTML = CH.map(([n, c], i) => `<div class="chan"><span class="nm"><i style="background:var(${c})"></i>${n}<small>${i < 2 ? (r ? "speed −100…100" : "speed") : "angle, degrees"}</small></span>
      <canvas id="rc-${i}" height="64"></canvas><div class="vals" id="rcv-${i}"></div></div>`).join("");
    CH.forEach((_, i) => $("#rc-" + i).onclick = ev => { const b = ev.target.getBoundingClientRect(); rSeek(((ev.clientX - b.left) / b.width) * rT()); });
    $("#r-legend").innerHTML = (r ? '<span><i style="border-top-style:dashed"></i>Model output</span><span><i style="border-color:#9097b5;border-top-width:2px"></i>Sent to the motor</span>' : "")
      + '<span><i style="border-color:var(--pink)"></i>Measured (channel colour)</span>' + (r ? '<span><i style="border-color:rgba(27,42,89,.25);border-top-width:1px"></i>New action chunk</span>' : '<span>Her motor log: 48 points across the demo</span>');
    rStats(); rSide(); rList(); rDraw();
  }
  const rT = () => cur.kind === "r" ? cur.r.m.T : cur.e.dur;
  const rNow = () => {
    if (cur.kind === "d") return (dk / 9) * cur.e.dur;
    const f = $("#rv-front"); return f && f.duration ? (f.currentTime / f.duration) * cur.r.m.T : 0;
  };
  function rSeek(t) {
    if (!cur) return;
    if (cur.kind === "d") { dStop(); dShow(Math.round((t / cur.e.dur) * 9)); return; }
    const v = rv(); if (v.f.duration) v.f.currentTime = v.t.currentTime = Math.max(0, Math.min(cur.r.m.T, t)) / cur.r.m.T * v.f.duration;
  }
  function dShow(k) {
    dk = Math.max(0, Math.min(9, k));
    $("#rd-top").src = `assets/eps/${cur.e.id}/t${pad(dk, 2)}.jpg`; $("#rd-front").src = `assets/eps/${cur.e.id}/f${pad(dk, 2)}.jpg`;
    $$("#r-strip img").forEach(im => im.classList.toggle("on", +im.dataset.k === dk));
  }
  function dStop() { clearInterval(dTimer); dTimer = null; $("#r-play").textContent = "Play"; }
  function rPause() { if (!cur) return; if (cur.kind === "d") dStop(); else { const v = rv(); v.f?.pause(); v.t?.pause(); $("#r-play").textContent = "Play"; } }
  $("#r-play").onclick = () => {
    if (!cur) return;
    if (cur.kind === "d") {
      if (dTimer) return dStop();
      $("#r-play").textContent = "Pause";
      dTimer = setInterval(() => dShow((dk + 1) % 10), 700 / +$("#r-rate").value);
      return;
    }
    const v = rv();
    if (v.f.paused) { if (v.f.ended) rSeek(0); v.f.play().catch(() => {}); v.t.play().catch(() => {}); $("#r-play").textContent = "Pause"; } else rPause();
  };
  const rStep = d => {
    if (!cur) return;
    if (cur.kind === "d") { dStop(); return dShow(dk + d); }
    rPause(); const f = cur.r.full, k = Math.max(0, Math.min(f.length - 1, idxAt(f, rNow() + 1e-4) + d)); rSeek(f[k][0] + 1e-3);
  };
  $("#r-prev").onclick = () => rStep(-1); $("#r-next").onclick = () => rStep(1);
  $("#r-rate").onchange = e => { const v = rv(); if (v.f) v.f.playbackRate = v.t.playbackRate = +e.target.value; if (dTimer) { dStop(); $("#r-play").click(); } };
  $("#r-scrub").oninput = e => cur && rSeek((e.target.value / 1000) * rT());
  function rDraw() {
    if (!cur || !$("#v-runs").classList.contains("on")) return;
    const t = rNow(), T = rT();
    if (cur.kind === "r") {
      const f = cur.r.full, k = idxAt(f, t), row = f[k], vl = f.filter(x => x[13]).map(x => x[0]);
      CH.forEach(([, c], i) => {
        chart($("#rc-" + i), { h: 64, xMax: T, vlines: vl, playhead: row[0], lines: [
          { pts: f.map(x => [x[0], x[5 + i]]), color: "#9097b5", width: 1.5, alpha: .8 },
          { pts: f.map(x => [x[0], x[1 + i]]), color: css("--navy"), dash: [5, 4], width: 1.4, alpha: .8 },
          { pts: f.map(x => [x[0], x[9 + i]]), color: css(c), width: 2.5 }] });
        $("#rcv-" + i).innerHTML = `<span>model <b>${fmt(row[1 + i])}</b></span><span>sent <b>${fmt(row[5 + i])}</b></span><span>measured <b>${fmt(row[9 + i], 0)}</b></span>`;
      });
      $("#r-time").textContent = `${fmt(row[0], 2)} s · step ${k + 1} / ${f.length}`;
      const v = rv(); if (v.f && Math.abs(v.t.currentTime - v.f.currentTime) > .3 && !v.f.paused) v.t.currentTime = v.f.currentTime;
    } else {
      const s = dSeries(cur.e), k = idxAt(s, t + 1e-6), row = s[k];
      CH.forEach(([, c], i) => {
        chart($("#rc-" + i), { h: 64, xMax: T, playhead: t, lines: [{ pts: s.map(x => [x[0], x[1 + i]]), color: css(c), width: 2.5 }] });
        $("#rcv-" + i).innerHTML = `<span>measured <b>${fmt(row[1 + i], 0)}</b></span>`;
      });
      $("#r-time").textContent = `${fmt(t, 1)} s · frame ${dk + 1} / 10`;
    }
    if (document.activeElement !== $("#r-scrub")) $("#r-scrub").value = Math.round((t / T) * 1000);
  }
  function tiles(el, rows) {
    el.innerHTML = rows.map(([v, k, cls]) => `<div class="tile ${cls || ""}"><b>${v}</b><span>${esc(k)}</span></div>`).join("");
  }
  function rStats() {
    if (cur.kind === "r") {
      const m = cur.r.m;
      tiles($("#r-stats"), [
        [`${fmt(m.T)}<small> s</small>`, `${m.n} steps`], [`${fmt(m.hz)}<small> Hz</small>`, "control rate"],
        [m.closeT != null ? `${fmt(m.closeT)}<small> s</small>` : "never", "gripper closed at"], [m.liftT != null ? `${fmt(m.liftT)}<small> s</small>` : "never", "arm lifted at"],
        [`${m.chunks}`, `action chunks · ${fmt(m.n / m.chunks)} steps each`], [`${Math.round(m.max)}<small> ms</small>`, `longest step, at ${fmt(m.maxAt)} s`, m.max > 4 * m.med ? "warn" : ""],
        [`${m.wheel[0]}° / ${m.wheel[1]}°`, "wheel travel, left / right"], [m.final.map(Math.round).join(" / "), "final L / R / arm / grip"]]);
    } else {
      const e = cur.e, m = dMetrics(e);
      tiles($("#r-stats"), [
        [`${fmt(e.dur)}<small> s</small>`, `${e.steps} steps`], [`${e.fps}<small> fps</small>`, "recording rate"],
        [m.closeT != null ? `${fmt(m.closeT)}<small> s</small>` : "never", "gripper closed at"], [m.liftT != null ? `${fmt(m.liftT)}<small> s</small>` : "never", "arm lifted at"],
        [`${fmt(e.skew)}<small> ms</small>`, "camera timing skew", e.skew > 13 ? "warn" : ""], [`${fmt(e.camAge)}<small> ms</small>`, "camera frame age", e.camAge > 20 ? "warn" : ""],
        [`${e.missing}`, "missing frames", e.missing ? "warn" : ""], [`spot ${e.pos}`, `${e.batch} · ${e.time}`]]);
    }
  }
  function rSide() {
    if (cur.kind === "r") {
      const m = cur.r.m;
      $("#r-side-h").textContent = "Control loop timing";
      $("#r-side").innerHTML = `<canvas class="plain" id="r-dt" height="130"></canvas><p class="muted" style="font-size:13px;font-weight:700;margin:8px 0 12px" id="r-dt-note"></p>
        <dl class="kv2">${Object.entries(cur.r.config).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v ?? "null")}</dd>`).join("")}</dl>`;
      const cv = $("#r-dt"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 130;
      cv.width = w * dpr; cv.height = h * dpr;
      const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const cap = Math.max(m.p95 * 2.5, m.med * 3), bw = w / m.dts.length;
      m.dts.forEach((d, i) => { const bh = Math.min(1, d / cap) * (h - 18); g.fillStyle = d > 2 * m.med ? css("--pink") : "rgba(108,107,224,.45)"; g.fillRect(i * bw, h - bh, Math.max(1, bw - 1), bh); });
      const ym = h - (m.med / cap) * (h - 18);
      g.strokeStyle = css("--navy"); g.setLineDash([4, 4]); g.beginPath(); g.moveTo(0, ym); g.lineTo(w, ym); g.stroke(); g.setLineDash([]);
      g.fillStyle = css("--navy"); g.font = "800 11px " + css("--mono"); g.fillText(`median ${Math.round(m.med)} ms`, 6, ym - 5);
      if (m.max > cap) { g.fillStyle = css("--pink"); g.fillText(`▲ ${Math.round(m.max)} ms`, Math.min(w - 90, m.maxStep * bw + 4), 12); }
      const slow = m.dts.filter(d => d > 2 * m.med).length;
      $("#r-dt-note").textContent = `Median ${Math.round(m.med)} ms between steps (${fmt(1000 / m.med)} Hz), 95th percentile ${Math.round(m.p95)} ms. ${slow} step${slow === 1 ? "" : "s"} took over twice the median.`
        + (m.maxStep === 1 ? ` The longest (${Math.round(m.max)} ms) is the first step, which waits for the first action chunk.` : "");
    } else {
      const v = cur.e.v;
      $("#r-side-h").innerHTML = "Claude's verdict";
      $("#r-side").innerHTML = v
        ? `<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">${v.success ? '<span class="pill2 ok">Picked up</span>' : '<span class="pill2 bad">Missed</span>'}<span class="mono">${Math.round(v.confidence * 100)}% sure · decided at ${fmt(v.key_frame_s)} s · $${v.cost_usd.toFixed(3)}</span></div>
           <p style="margin:0;font-size:15px;font-weight:700;line-height:1.45">${esc(v.reason)}</p>`
        : `<p style="margin:0;font-size:15px;font-weight:800" class="muted">Not judged yet. This demo is from ${esc(cur.e.batch)}; Claude has judged Batch A so far (50 demos).</p>`;
    }
  }
  addEventListener("keydown", e => {
    if (!$("#v-runs").classList.contains("on") || !cur || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); rStep(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); rStep(1); }
    else if (e.code === "Space") { e.preventDefault(); $("#r-play").click(); }
  });

  // ================= LABELS =================
  let reviews = store.get("loopvla-reviews", {});
  const eff = l => (reviews[l.name] === "flip" ? !l.success : l.success);
  const CUP = { held_lifted: "Held and lifted", upright_free: "Standing, not held", out_of_view: "Out of view" };
  const groupOf = l => (l.spot ? "Spot " + l.spot : l.group);
  const GROUPS = ["Spot 1", "Spot 2", "Spot 3", "Spot 4", "Spot 5", "Early sessions", "Demo episodes"];
  let sort = { k: "confidence", dir: 1 }, openRow = null, lInit = false;
  function labelsInit() {
    if (lInit) return; lInit = true;
    $("#lf-g").innerHTML = '<option value="">All</option>' + GROUPS.map(g => `<option>${g}</option>`).join("");
    ["lf-v", "lf-g", "lf-c", "lf-q"].forEach(id => $("#" + id).oninput = () => { $("#lf-cv").textContent = $("#lf-c").value + "%"; lTable(); });
    ["c-conf", "c-rev"].forEach(id => $("#" + id).oninput = curate);
    $$("#l-table [data-sort]").forEach(b => b.onclick = () => {
      sort = { k: b.dataset.sort, dir: sort.k === b.dataset.sort ? -sort.dir : 1 };
      $$("#l-table [data-sort]").forEach(x => x.textContent = x.textContent.replace(/ [▲▼]$/, ""));
      b.textContent += sort.dir > 0 ? " ▲" : " ▼"; lTable();
    });
  }
  function labelsRender() {
    const n = L.labels.length, ok = L.labels.filter(eff).length, cost = L.labels.reduce((a, l) => a + l.cost_usd, 0), low = L.labels.filter(l => l.confidence < .85).length;
    tiles($("#l-tiles"), [
      [`${n}`, "attempts judged"], [`${ok} <small>(${Math.round(100 * ok / n)}%)</small>`, "picked up the cup", "hot"],
      [`${Math.round(L.summary.mean_confidence * 100)}%`, "mean confidence"], [`${low}`, "below 85%: review these first", low ? "warn" : ""],
      [`${L.summary.label_agreement.agree} / ${L.summary.label_agreement.labelled}`, "agree with a human label"],
      [`$${cost.toFixed(2)}`, `in total · $${(cost / n).toFixed(3)} per attempt`], [`${DEMOS.length - DEMOS.filter(d => d.v).length}`, "demos not judged yet (Batch B)"]]);
    const by = GROUPS.map(g => { const a = L.labels.filter(l => groupOf(l) === g); return [g, a.filter(eff).length, a.length]; }).filter(x => x[2]);
    const mx = Math.max(...by.map(x => x[2]));
    $("#l-spots").innerHTML = by.map(([g, k, n]) => `<div class="hbar"><span>${g}</span><div class="track" style="width:${100 * n / mx}%"><i style="width:${100 * k / n}%;background:var(--s-arm)"></i><i style="width:${100 * (n - k) / n}%;background:var(--bad)"></i></div><span class="v">${k} / ${n}</span></div>`).join("")
      + `<p class="muted" style="font-size:13px;font-weight:700;margin:4px 0 0">Every miss is <span class="mono">did_not_reach_cup</span>: Neil never got the gripper to the cup. All of them are in the early sessions.</p>`;
    lHist(); curate(); lTable();
  }
  function lHist() {
    const cv = $("#l-hist"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 170;
    if (!w) return;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const lo = .7, step = .025, nb = 12, B = Array.from({ length: nb }, () => [0, 0]);
    L.labels.forEach(l => { const i = Math.max(0, Math.min(nb - 1, Math.floor((l.confidence - lo) / step + 1e-9))); B[i][eff(l) ? 0 : 1]++; });
    const mx = Math.max(...B.map(b => b[0] + b[1])), bw = (w - 8) / nb, base = h - 18;
    B.forEach(([s, f], i) => {
      const x = 4 + i * bw, hs = (s / mx) * (base - 6), hf = (f / mx) * (base - 6);
      g.fillStyle = css("--s-arm"); g.beginPath(); g.roundRect(x + 2, base - hs, bw - 4, hs, 6); g.fill();
      g.fillStyle = css("--bad"); g.beginPath(); g.roundRect(x + 2, base - hs - hf, bw - 4, hf, 6); g.fill();
    });
    g.fillStyle = css("--navy-2"); g.font = "800 11px " + css("--font");
    [.7, .8, .9, 1].forEach(v => g.fillText(Math.round(v * 100) + "%", Math.max(2, Math.min(w - 30, 4 + ((v - lo) / step) * bw - 10)), h - 3));
  }
  function curate() {
    const thr = +$("#c-conf").value / 100, only = $("#c-rev").checked;
    $("#c-v").textContent = Math.round(thr * 100) + "%";
    let inc = 0, missed = 0, low = 0, unrev = 0;
    L.labels.forEach(l => { if (!eff(l)) missed++; else if (l.confidence < thr) low++; else if (only && !reviews[l.name]) unrev++; else inc++; });
    tiles($("#c-tiles"), [[`${inc}`, "go into the next set", "hot"], [`${missed}`, "left out: missed"], [`${low}`, "left out: not sure enough", low ? "warn" : ""], [`${unrev}`, only ? "left out: not reviewed" : "need review (rule off)"]]);
  }
  function lTable() {
    const fv = $("#lf-v").value, fg = $("#lf-g").value, fc = +$("#lf-c").value / 100, q = $("#lf-q").value.trim().toLowerCase();
    const rows = L.labels.filter(l => (fv === "" || String(+eff(l)) === fv) && (!fg || groupOf(l) === fg) && l.confidence <= fc + 1e-9 && (!q || l.reason.toLowerCase().includes(q)));
    const key = l => sort.k === "success" ? +eff(l) : sort.k === "group" ? groupOf(l) : l[sort.k];
    rows.sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * sort.dir);
    const rv2 = l => reviews[l.name] === "ok" ? '<span class="pill2 ok">Confirmed</span>' : reviews[l.name] === "flip" ? '<span class="pill2 ai">Flipped</span>' : '<span class="muted">—</span>';
    $("#l-table").tBodies[0].innerHTML = rows.map(l => {
      const main = `<tr class="row" data-n="${esc(l.name)}" tabindex="0"><td><b>${groupOf(l)}</b> <span class="mono muted" style="font-size:12px">${tOf(l)}</span></td>
        <td>${eff(l) ? '<span class="pill2 ok">Picked up</span>' : '<span class="pill2 bad">Missed</span>'}</td><td class="num">${Math.round(l.confidence * 100)}%</td>
        <td>${CUP[l.cup] || esc(l.cup)}</td><td class="num">${fmt(l.key_frame_s)} s</td><td class="num">${fmt(l.duration_s)} s</td><td class="num">$${l.cost_usd.toFixed(3)}</td><td>${rv2(l)}</td></tr>`;
      const det = openRow === l.name ? `<tr class="detail"><td colspan="8"><div style="display:grid;gap:10px;max-width:120ch"><span>${esc(l.reason)}</span>
        <span class="mono muted" style="font-size:12px">${esc(l.name)}${l.human_label != null ? ` · human label: ${l.human_label ? "picked up" : "missed"}` : ""}</span>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn2" data-rv="ok">Confirm verdict</button><button class="btn2" data-rv="flip">Flip to ${l.success ? "missed" : "picked up"}</button>${reviews[l.name] ? '<button class="btn2" data-rv="">Clear review</button>' : ""}</div></div></td></tr>` : "";
      return main + det;
    }).join("") || `<tr><td colspan="8" class="muted">No verdicts match these filters.</td></tr>`;
    $$("#l-table tr.row").forEach(tr => { const tog = () => { openRow = openRow === tr.dataset.n ? null : tr.dataset.n; lTable(); }; tr.onclick = tog; tr.onkeydown = e => { if (e.key === "Enter") tog(); }; });
    $$("#l-table [data-rv]").forEach(b => b.onclick = e => { e.stopPropagation(); if (b.dataset.rv) reviews[openRow] = b.dataset.rv; else delete reviews[openRow]; store.set("loopvla-reviews", reviews); labelsRender(); });
    $("#l-count").textContent = `showing ${rows.length} · reviewed ${Object.keys(reviews).length} of ${L.labels.length}`;
  }

  // ================= MODELS =================
  const jobs = [
    { id: "181436", model: "v1 · pick_cup", ep: 50, steps: 10000, status: "Done", note: "" },
    { id: "181719", model: "training run", ep: null, steps: null, status: "Done", note: "final loss 0.09" },
    { id: "182076", model: "v3 · pick_cup_angle_182076", ep: null, steps: null, status: "Done", note: "" },
  ];
  let confirmV = null, queued = 0;
  function mRender() {
    syncV3();
    $("#m-cards").innerHTML = MODELS.map(m => {
      const isProd = prod === m.v;
      const act = isProd ? '<span class="pill2 ai">Driving Neil now</span>'
        : m.v === "Base" ? '<button class="btn2" disabled>Not trained for Neil</button>'
        : m.rate == null ? '<button class="btn2" disabled>Not tested on Neil yet</button>'
        : confirmV === m.v ? `<span style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-weight:900;color:var(--pink-text)">Switch Neil to ${m.v}?<button class="btn2 primary" data-dep="${m.v}">Deploy</button><button class="btn2" data-cancel>Cancel</button></span>`
        : `<button class="btn2 purple" data-ask="${m.v}">Deploy ${m.v}</button>`;
      return `<article class="mc lg${isProd ? " prod" : ""}"><h4>${m.v}${isProd ? ' <span class="pill2 ai">In production</span>' : ""}</h4><span class="nm">${esc(m.name)}</span>
        <div class="rate${m.rate == null ? " none" : ""}">${m.rate == null ? "not tested yet" : Math.round(m.rate * 100) + "%"}${m.rate == null ? "" : m.real ? '<span class="tag-real">measured</span>' : '<span class="tag-demo">demo value</span>'}</div>
        <dl class="kv2"><dt>grasp rate</dt><dd>${m.n || (m.rate == null ? "—" : "not measured on Neil")}</dd><dt>actions</dt><dd>${esc(m.mode)}</dd><dt>trained on</dt><dd>${esc(m.trained)}</dd><dt>Athena job</dt><dd>${esc(m.job)}</dd></dl>
        <div>${act}</div></article>`;
    }).join("");
    $$("#m-cards [data-ask]").forEach(b => b.onclick = () => { confirmV = b.dataset.ask; mRender(); });
    $$("#m-cards [data-cancel]").forEach(b => b.onclick = () => { confirmV = null; mRender(); });
    $$("#m-cards [data-dep]").forEach(b => b.onclick = () => { prod = b.dataset.dep; confirmV = null; mRender(); });
    // v2 on Neil vs the human demos it learned from (all measured)
    const g = RUNS.filter(r => r.outcome === "grasped"), dm = DEMOS.map(dMetrics);
    const judged = DEMOS.filter(d => d.v), dOk = judged.filter(d => d.v.success).length;
    const rows = [
      ["Picked up the cup", `${g.length} / ${RUNS.length} (${Math.round(100 * g.length / RUNS.length)}%)`, `${dOk} / ${judged.length} judged (${Math.round(100 * dOk / judged.length)}%)`],
      ["Gripper closes at (median)", `${fmt(median(g.map(r => r.m.closeT)))} s`, `${fmt(median(dm.map(m => m.closeT).filter(x => x != null)))} s`],
      ["Arm lifts the cup at (median)", `${fmt(median(g.map(r => r.m.liftT).filter(x => x != null)))} s`, `${fmt(median(dm.map(m => m.liftT).filter(x => x != null)))} s`],
      ["Length of a try (median)", `${fmt(median(RUNS.map(r => r.m.T)))} s`, `${fmt(median(DEMOS.map(d => d.dur)))} s`],
      ["Steps per second", `${fmt(median(RUNS.map(r => r.m.hz)))}`, `${fmt(median(DEMOS.map(d => d.fps)), 0)}`],
      ["Drove past the cup", `${RUNS.filter(r => r.outcome === "missed_cup").length} / ${RUNS.length}`, `0 / ${judged.length}`],
    ];
    $("#m-vs").innerHTML = `<thead><tr><th>Measure</th><th class="num">v2 on Neil</th><th class="num">Human demos</th></tr></thead><tbody>` +
      rows.map(([k, a, b]) => `<tr><td><b>${k}</b></td><td class="num">${a}</td><td class="num">${b}</td></tr>`).join("") + "</tbody>";
    mJobs();
  }
  function mJobs() {
    const live = $("#tLbl")?.textContent === "Training now";
    const rows = jobs.concat(live ? [{ id: "auto", model: "v3 · started by LoopVLA", ep: P.S.demos, steps: 10000, status: "Training", note: $("#tVal").textContent }] : []);
    $("#m-jobs").innerHTML = `<thead><tr><th>Job</th><th>Model</th><th class="num">Demos</th><th class="num">Steps</th><th>Status</th></tr></thead><tbody>` +
      rows.map(j => `<tr><td class="mono">${esc(j.id)}</td><td>${esc(j.model)}${j.note ? `<br><span class="muted mono" style="font-size:12px">${esc(j.note)}</span>` : ""}</td>
        <td class="num">${j.ep ?? "—"}</td><td class="num">${j.steps ? j.steps.toLocaleString("en-US") : "—"}</td>
        <td>${j.status === "Done" ? '<span class="pill2 ok">Done</span>' : j.status === "Queued" ? '<span class="pill2 wait">Queued</span>' : `<span class="pill2 ai"><span class="dot"></span>${j.status}</span>`}</td></tr>`).join("") + "</tbody>";
    jCmd();
  }
  function jCmd() {
    const st = +$("#j-steps").value || 10000, b = +$("#j-batch").value || 64, ds = `pick_cup_loop_v${4 + queued}`;
    $("#j-cmd").textContent = `# ${ds}: ${P.S.demos} demos · start from ${$("#j-base").value}\nrsync -av data/${ds} your.name@athena.technion.ac.il:$VLA/data/\nsbatch train_neil.job ${st} ${b} ${ds}`;
  }
  ["j-base", "j-steps", "j-batch"].forEach(id => $("#" + id).oninput = jCmd);
  $("#j-go").onclick = () => {
    queued++;
    jobs.push({ id: `queued-${queued}`, model: `v${3 + queued} · from ${$("#j-base").value.split(" ")[0]}`, ep: P.S.demos, steps: +$("#j-steps").value, status: "Queued", note: "" });
    $("#j-msg").textContent = "Added to the list. Nothing was sent to Athena.";
    mJobs();
  };
  $("#j-copy").onclick = () => {
    const sel = () => { const r = document.createRange(); r.selectNodeContents($("#j-cmd")); const s = getSelection(); s.removeAllRanges(); s.addRange(r); $("#j-msg").textContent = "Selected: press Ctrl+C."; };
    try { navigator.clipboard.writeText($("#j-cmd").textContent).then(() => ($("#j-msg").textContent = "Copied."), sel); } catch { sel(); }
  };

  // ---------- Page hooks from app.js ----------
  let rInit = false;
  window.LAB = {
    shown(v) {
      if (v === "ops") { ov.f.play().catch(() => {}); ov.t.play().catch(() => {}); } else { ov.f.pause(); ov.t.pause(); }
      if (v !== "runs") rPause();
      if (v === "runs" && !rInit) { rInit = true; rList(); rSelect(RUNS[0].id); }
      if (v === "runs" && cur) requestAnimationFrame(() => { rSide(); rDraw(); });
      if (v === "labels") { labelsInit(); requestAnimationFrame(labelsRender); }
      if (v === "models") mRender();
    },
  };
  let sig = "";
  setInterval(() => {   // keep Models in step with the overnight upgrade
    const s = `${P.S.version}|${$("#tLbl")?.textContent}|${P.S.demos}`;
    if (s !== sig && $("#v-models").classList.contains("on")) { sig = s; mRender(); }
  }, 1000);
  (function loop() { oFrame(); rDraw(); requestAnimationFrame(loop); })();
  addEventListener("resize", () => { if ($("#v-labels").classList.contains("on")) lHist(); if ($("#v-runs").classList.contains("on") && cur) rSide(); });
  oLoad(0); oRender();
  const cv = $(".tab.on")?.dataset.view; if (cv && P.LAB_VIEWS.includes(cv)) window.LAB.shown(cv);
})();
