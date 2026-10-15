/* LoopVLA engineering tabs: Live, Runs, Analysis, Labels, Jobs, Models. Plain JS, no build step.
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
    let open = false, closeT = null, liftT = null;
    for (const row of f) {
      if (row[12] > -35) open = true;
      if (open && closeT == null && row[12] <= CLOSED) closeT = row[0];
      if (closeT != null && liftT == null && row[11] <= LIFTED) liftT = row[0];
    }
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
    ...(L.tests || []).map(p => ({ key: p.id, kind: "p", p, title: "Pipeline test " + hhmmss(p.id), disabled: !p.steps,
      sub: p.steps ? `${p.checkpoint} · ${p.mode} · ${p.steps} steps · 14 Oct` : "no steps recorded", outcome: "test" })),
  ];
  let cur = null, rf = "all", dk = 0, dTimer = null;
  const chip = o => ({ grasped: '<span class="pill2 ok">Grasped</span>', missed_cup: '<span class="pill2 bad">Missed</span>', aborted: '<span class="pill2 wait">Stopped</span>',
    picked: '<span class="pill2 ok">Picked up</span>', missed: '<span class="pill2 bad">Missed</span>', unjudged: '<span class="pill2 wait">Not judged</span>', test: '<span class="pill2 lab">Dry run</span>' }[o]);
  function rList() {
    $("#rlist").innerHTML = ITEMS.filter(i => rf === "all" || i.kind === rf).map(i =>
      `<button class="ritem" data-key="${i.key}" ${i.disabled ? "disabled" : ""} aria-current="${cur?.key === i.key}"><span class="t1">${chip(i.outcome)}${esc(i.title)}</span><span class="t2">${esc(i.sub)}</span></button>`).join("");
    $$("#rlist .ritem").forEach(b => b.onclick = () => rSelect(b.dataset.key));
  }
  $$("#rf .chip").forEach(c => c.onclick = () => { rf = c.dataset.rf; $$("#rf .chip").forEach(x => x.classList.toggle("on", x === c)); rList(); });
  const rv = () => ({ f: $("#rv-front"), t: $("#rv-top") });
  function rSelect(key) {
    cur = ITEMS.find(i => i.key === key); if (!cur || cur.disabled) return;
    clearInterval(dTimer); dTimer = null; dk = 0;
    const r = cur.kind === "r", d = cur.kind === "d", p = cur.kind === "p";
    $("#r-title").textContent = cur.title;
    $("#r-chips").innerHTML = chip(cur.outcome) + (r ? `<span class="pill2 wait">${esc(cur.r.model)}</span><span class="pill2 wait">${esc(cur.r.config.action_mode)} actions</span>`
      : d ? `<span class="pill2 wait">teleoperated · spot ${cur.e.pos}</span><span class="pill2 wait">${esc(cur.e.batch)}</span>`
      : `<span class="pill2 wait">${esc(cur.p.checkpoint)}</span><span class="pill2 wait">${esc(cur.p.device)} · ${esc(cur.p.mode)}</span><span class="pill2 wait">task "${esc(cur.p.task)}"</span>`);
    $("#r-cams").innerHTML = r
      ? `<div class="cam"><video id="rv-front" muted playsinline preload="auto" src="assets/lab/${cur.r.id}/front.mp4"></video><span class="lbl">Neil's eye</span></div>
         <div class="cam wide" style="align-self:start"><video id="rv-top" muted playsinline preload="auto" src="assets/lab/${cur.r.id}/top.mp4"></video><span class="lbl">Top camera</span></div>`
      : d ? `<div class="cam"><img id="rd-front" alt="Neil's eye"><span class="lbl">Neil's eye</span></div>
         <div class="cam wide" style="align-self:start"><img id="rd-top" alt="Top camera"><span class="lbl">Top camera</span></div>`
      : `<div class="pane-note" style="grid-column:1/-1">The policy server answered on a recorded session (<span class="mono">${esc(cur.p.replay)}</span>) and the
         actions were logged, not sent: Neil did not move. This run measures the pipeline, not the robot.</div>`;
    $("#r-strip").hidden = !d;
    $("#r-transport").hidden = p;
    if (d) {
      $("#r-strip").innerHTML = Array.from({ length: 10 }, (_, k) => `<img data-k="${k}" src="assets/eps/${cur.e.id}/t${pad(k, 2)}.jpg" alt="frame ${k + 1}">`).join("");
      $$("#r-strip img").forEach(im => im.onclick = () => { dStop(); dShow(+im.dataset.k); });
      dShow(0);
    } else if (r) {
      const v = rv(); v.f.playbackRate = v.t.playbackRate = +$("#r-rate").value;
      v.f.addEventListener("ended", () => { $("#r-play").textContent = "Play"; });
    }
    $("#r-play").textContent = "Play";
    if (p) {
      const c = cur.p.chunks;
      $("#r-chans").innerHTML = `<div class="chan"><span class="nm">Round trip<small>per action chunk</small></span><canvas id="rc-lat" height="90"></canvas><div class="vals" id="rcv-lat"></div></div>`;
      $("#r-legend").innerHTML = '<span><i style="border-color:var(--pink)"></i>Round trip (laptop to server and back)</span><span><i style="border-color:var(--purple)"></i>Model inference on the server</span>';
      requestAnimationFrame(() => {
        const cv = $("#rc-lat"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 90;
        cv.width = w * dpr; cv.height = h * dpr;
        const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
        const mx = Math.max(...c.map(x => x.round_trip_ms || 0), 1), bw = Math.min(80, (w - 10) / Math.max(1, c.length));
        c.forEach((x, i) => {
          const hr = (x.round_trip_ms / mx) * (h - 22), hi = ((x.infer_ms || 0) / mx) * (h - 22);
          g.fillStyle = css("--pink"); g.beginPath(); g.roundRect(6 + i * bw, h - 16 - hr, bw * .42, hr, 5); g.fill();
          g.fillStyle = css("--purple"); g.beginPath(); g.roundRect(6 + i * bw + bw * .46, h - 16 - hi, bw * .42, hi, 5); g.fill();
          g.fillStyle = css("--navy-2"); g.font = "800 10px " + css("--mono"); g.fillText(`#${i + 1}`, 6 + i * bw, h - 3);
        });
        $("#rcv-lat").innerHTML = `<span>median <b>${fmt(median(c.map(x => x.round_trip_ms)) / 1000, 2)} s</b></span><span>chunks <b>${c.length}</b></span>`;
      });
    } else {
      $("#r-chans").innerHTML = CH.map(([n, c], i) => `<div class="chan"><span class="nm"><i style="background:var(${c})"></i>${n}<small>${i < 2 ? "speed" : "angle, degrees"}</small></span>
        <canvas id="rc-${i}" height="64"></canvas><div class="vals" id="rcv-${i}"></div></div>`).join("");
      CH.forEach((_, i) => $("#rc-" + i).onclick = ev => { const b = ev.target.getBoundingClientRect(); rSeek(((ev.clientX - b.left) / b.width) * rT()); });
      $("#r-legend").innerHTML = (r ? '<span><i style="border-top-style:dashed"></i>Model output</span><span><i style="border-color:#9097b5;border-top-width:2px"></i>Sent to the motor</span>' : "")
        + '<span><i style="border-color:var(--pink)"></i>Measured (channel colour)</span>' + (r ? '<span><i style="border-color:rgba(27,42,89,.25);border-top-width:1px"></i>New action chunk</span>' : '<span>Motor log: 48 points across the demo</span>');
    }
    rStats(); rSide(); rFiles(); rList(); rDraw();
  }
  const rT = () => cur.kind === "r" ? cur.r.m.T : cur.kind === "d" ? cur.e.dur : (cur.p.duration_s || 1);
  const rNow = () => {
    if (cur.kind === "p") return 0;
    if (cur.kind === "d") return (dk / 9) * cur.e.dur;
    const f = $("#rv-front"); return f && f.duration ? (f.currentTime / f.duration) * cur.r.m.T : 0;
  };
  function rSeek(t) {
    if (!cur || cur.kind === "p") return;
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
    if (!cur || cur.kind === "p" || !$("#v-runs").classList.contains("on")) return;
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
    if (cur.kind === "p") {
      const p = cur.p, c = p.chunks;
      return tiles($("#r-stats"), [
        [`${fmt(p.duration_s)}<small> s</small>`, `${p.steps} steps at ${p.fps} fps`], [`${c.length}`, `action chunks of ${c[0]?.chunk_size ?? "—"}`],
        [`${fmt(median(c.map(x => x.round_trip_ms)) / 1000, 2)}<small> s</small>`, "round trip per chunk (median)", median(c.map(x => x.round_trip_ms)) > 5000 ? "warn" : ""],
        [`${fmt(median(c.map(x => x.infer_ms || 0)) / 1000, 2)}<small> s</small>`, "model inference per chunk"],
        [`${p.late_ticks ?? "—"}`, "late control ticks"], [`${fmt(p.cam_age_ms?.pi, 0)} / ${fmt(p.cam_age_ms?.external, 0)}<small> ms</small>`, "camera frame age, robot / top"]]);
    }
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
    if (cur.kind === "p") {
      $("#r-side-h").textContent = "Inference per chunk";
      $("#r-side").innerHTML = `<div class="tbl-wrap"><table class="t2"><thead><tr><th>Chunk</th><th class="num">Asked at step</th><th class="num">Answered at step</th><th class="num">Round trip</th><th class="num">Inference</th><th class="num">Decode</th></tr></thead><tbody>` +
        cur.p.chunks.map((c, i) => `<tr><td>#${i + 1}</td><td class="num">${c.obs_step}</td><td class="num">${c.reply_step ?? "—"}</td><td class="num">${fmt(c.round_trip_ms, 0)} ms</td><td class="num">${fmt(c.infer_ms, 0)} ms</td><td class="num">${fmt(c.decode_ms, 1)} ms</td></tr>`).join("") + "</tbody></table></div>";
      return;
    }
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
  const SRC_SUB = { "Batch A": ["first position", "second position", "third position", "fourth position", "fifth position"],
                   "Batch B": ["first_spot", "second", "third position", "fourth", "fifht"] };
  const SRC_DIR = { "Batch A": "episodes/all sessions", "Batch B": "all poistions 2" };
  function fileRow(label, path, href) {
    return `<div class="frow"><span class="fl">${esc(label)}</span><span class="mono fp">${esc(path)}</span>
      ${href ? `<a class="btn2" href="${esc(href)}" target="_blank" rel="noopener">Open</a>` : '<span class="btn2 off">on that machine</span>'}
      <button class="btn2" data-copy="${esc(path)}">Copy path</button></div>`;
  }
  function rFiles() {
    let rows = [], sub = "";
    if (cur.kind === "r") {
      const id = cur.r.id, base = `dashboard_sample_data/vla_rollouts/${id}`;
      sub = "in Neil-LabAI, branch claude/project-thread-4sp9ds";
      rows = [["Motor log, one line per step", `${base}/steps.jsonl`, `assets/lab/${id}/steps.jsonl`], ["Run settings", `${base}/run.json`, `assets/lab/${id}/run.json`],
        ["Robot camera", `${base}/front.mp4`, `assets/lab/${id}/front.mp4`], ["Top camera", `${base}/top.mp4`, `assets/lab/${id}/top.mp4`],
        ["Model it ran", cur.r.config.policy, null]];
    } else if (cur.kind === "d") {
      const e = cur.e, dir = `${SRC_DIR[e.batch]}/${SRC_SUB[e.batch][e.pos - 1]}/session_${e.id}`;
      sub = "recorded on Neil, 14 Oct";
      rows = [["Session folder (steps.jsonl, pi/, external/)", dir + "/", null], ["Motor log", `${dir}/steps.jsonl`, null],
        ["Top camera frames used here", `loopvla-dashboard/assets/eps/${e.id}/t00.jpg … t09.jpg`, `assets/eps/${e.id}/t05.jpg`],
        ["Robot camera frames used here", `loopvla-dashboard/assets/eps/${e.id}/f00.jpg … f09.jpg`, `assets/eps/${e.id}/f05.jpg`]];
      if (e.v) rows.push(["Claude's verdict", `output/classifier/…/attempts/${e.v.name}.json`, `assets/lab/labels/${e.v.name}.json`], ["Session Claude judged", e.v.source || "—", null]);
    } else {
      const id = cur.p.id, base = `logs/${id}`;
      sub = "in Neil-LabAI/logs on the laptop that ran it (not in git)";
      rows = [["Inference log, one line per chunk", `${base}/inference.jsonl`, `assets/lab/tests/${id}/inference.jsonl`], ["Server and spec", `${base}/policy.json`, `assets/lab/tests/${id}/policy.json`],
        ["Run info and camera timing", `${base}/info.json`, `assets/lab/tests/${id}/info.json`], ["Motor and camera log", `${base}/steps.jsonl`, null], ["Session it replayed", cur.p.replay || "—", null]];
    }
    $("#r-files-sub").textContent = sub;
    $("#r-files").innerHTML = rows.map(([a, b, c]) => fileRow(a, b, c)).join("");
    $$("#r-files [data-copy]").forEach(bt => bt.onclick = () => copyText(bt.dataset.copy, bt));
  }
  function copyText(t, btn) {
    const done = () => { const o = btn.textContent; btn.textContent = "Copied"; setTimeout(() => (btn.textContent = o), 1200); };
    try { navigator.clipboard.writeText(t).then(done, () => prompt("Copy:", t)); } catch { prompt("Copy:", t); }
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
  let confirmV = null;
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
  }
  // ================= ANALYSIS: groups of runs =================
  // One record per run, rollouts and demos alike: time in seconds, motor curves, timing and outcome.
  const REC = [
    ...RUNS.map(r => ({ key: r.id, kind: "r", name: "Rollout " + hhmmss(r.id), T: r.m.T, closeT: r.m.closeT, liftT: r.m.liftT, hz: r.m.hz,
      ok: r.outcome === "grasped", outcome: r.outcome, finalGrip: r.m.final[3],
      curves: { grip: r.full.map(x => [x[0], x[12]]), arm: r.full.map(x => [x[0], x[11]]), wheel: r.full.map(x => [x[0], (x[5] + x[6]) / 2]) } })),
    ...DEMOS.map(e => {
      const s = dSeries(e), m = dMetrics(e);
      return { key: e.id, kind: "d", name: "Demo " + e.no, T: e.dur, closeT: m.closeT, liftT: m.liftT, hz: e.fps, pos: e.pos, batch: e.batch,
        ok: e.v ? e.v.success : null, finalGrip: s[s.length - 1][4],
        curves: { grip: s.map(x => [x[0], x[4]]), arm: s.map(x => [x[0], x[3]]), wheel: s.map(x => [x[0], x[1] == null || x[2] == null ? null : (x[1] + x[2]) / 2]) } };
    }),
  ];
  const GROUPS_AN = [
    ["v2 rollouts, 15 Oct", x => x.kind === "r"],
    ["v2 rollouts that grasped", x => x.kind === "r" && x.ok],
    ["v2 rollouts that missed", x => x.kind === "r" && !x.ok],
    ["All human demos", x => x.kind === "d"],
    ...[1, 2, 3, 4, 5].map(k => [`Demos from spot ${k}`, x => x.kind === "d" && x.pos === k]),
    ["Demos Claude judged (Batch A)", x => x.kind === "d" && x.batch === "Batch A"],
    ["Demos not judged yet (Batch B)", x => x.kind === "d" && x.batch === "Batch B"],
  ];
  $("#an-a").innerHTML = $("#an-b").innerHTML = GROUPS_AN.map(([n], i) => `<option value="${i}">${esc(n)}</option>`).join("");
  $("#an-a").value = "0"; $("#an-b").value = "3";
  ["an-a", "an-b", "an-align", "an-each"].forEach(id => $("#" + id).onchange = anRender);
  const q3 = a => { const v = a.filter(x => x != null && !Number.isNaN(x)); return v.length ? [quant(v, .25), quant(v, .5), quant(v, .75)] : null; };
  const span = (a, d = 1, u = " s") => { const q = q3(a); return q ? `${fmt(q[1], d)}${u} <span class="muted">[${fmt(q[0], d)}–${fmt(q[2], d)}]</span>` : "—"; };
  function anSets() {
    const A = REC.filter(GROUPS_AN[+$("#an-a").value][1]), B = REC.filter(GROUPS_AN[+$("#an-b").value][1]);
    return { A, B, nA: GROUPS_AN[+$("#an-a").value][0], nB: GROUPS_AN[+$("#an-b").value][0] };
  }
  function anRender() {
    if (!$("#v-analysis").classList.contains("on")) return;
    const { A, B, nA, nB } = anSets(), align = $("#an-align").checked;
    $("#an-n").textContent = `A: ${A.length} runs · B: ${B.length} runs`;
    const succ = g => { const j = g.filter(x => x.ok != null); return j.length ? `${j.filter(x => x.ok).length} / ${j.length} <span class="muted">(${Math.round(100 * j.filter(x => x.ok).length / j.length)}%)</span>` : "not judged"; };
    const rows = [
      ["Runs", g => `${g.length}`], ["Picked up the cup", succ], ["Length of a try", g => span(g.map(x => x.T))],
      ["Gripper closes at", g => span(g.map(x => x.closeT))], ["Arm lifts the cup at", g => span(g.map(x => x.liftT))],
      ["Close to lift", g => span(g.map(x => (x.liftT != null && x.closeT != null ? x.liftT - x.closeT : null)))],
      ["Never closed the gripper", g => `${g.filter(x => x.closeT == null).length}`], ["Steps per second", g => span(g.map(x => x.hz), 1, "")],
      ["Gripper angle at the end", g => span(g.map(x => x.finalGrip), 0, "°")],
    ];
    $("#an-table").innerHTML = `<thead><tr><th>Measure</th><th class="num"><span class="sw a"></span>${esc(nA)}</th><th class="num"><span class="sw b"></span>${esc(nB)}</th></tr></thead><tbody>` +
      rows.map(([k, f]) => `<tr><td><b>${k}</b></td><td class="num">${f(A)}</td><td class="num">${f(B)}</td></tr>`).join("") + "</tbody>";
    anDots(A, B); anCurves(A, B, align); anRuns(A, B); anLatency();
  }
  function anDots(A, B) {
    const cv = $("#an-dots"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 230;
    if (!w) return;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const all = [...A, ...B].map(x => x.closeT).filter(x => x != null), mx = Math.max(10, ...all) * 1.08;
    const X = t => 70 + (t / mx) * (w - 90);
    g.strokeStyle = "rgba(27,42,89,.15)"; g.fillStyle = css("--navy-2"); g.font = "800 11px " + css("--font");
    for (let t = 0; t <= mx; t += mx > 30 ? 10 : 5) { g.beginPath(); g.moveTo(X(t), 10); g.lineTo(X(t), h - 24); g.stroke(); g.fillText(t + " s", X(t) - 8, h - 8); }
    [[A, "A", css("--pink"), 70], [B, "B", css("--purple"), 150]].forEach(([set, n, col, y]) => {
      g.fillStyle = css("--navy"); g.font = "900 15px " + css("--font"); g.fillText("Group " + n, 4, y + 5);
      set.forEach((x, i) => {
        if (x.closeT == null) return;
        const jy = y + ((i * 37) % 31) - 15;
        g.fillStyle = col; g.globalAlpha = .75; g.beginPath(); g.arc(X(x.closeT), jy, 6, 0, 7); g.fill(); g.globalAlpha = 1;
      });
      const md = median(set.map(x => x.closeT).filter(x => x != null));
      if (md != null) { g.fillStyle = css("--navy"); g.fillRect(X(md) - 2, y - 26, 4, 52); g.font = "800 12px " + css("--mono"); g.fillText(fmt(md) + " s", X(md) + 6, y - 18); }
      const never = set.filter(x => x.closeT == null).length;
      if (never) { g.fillStyle = css("--bad"); g.font = "800 12px " + css("--font"); g.fillText(`${never} never closed`, w - 110, y + 5); }
    });
  }
  function medianCurve(set, key, align, grid) {
    return grid.map(t => {
      const v = set.map(x => {
        const t0 = align ? x.closeT : 0;
        if (align && t0 == null) return null;
        const c = x.curves[key], tt = t + t0;
        if (tt < c[0][0] || tt > c[c.length - 1][0]) return null;
        return c[idxAt(c, tt)][1];
      }).filter(y => y != null);
      return [t, v.length >= Math.max(1, Math.ceil(set.length / 3)) ? median(v) : null];
    });
  }
  function anCurves(A, B, align) {
    const each = $("#an-each").checked;
    const keys = [["grip", "Gripper", "angle, degrees"], ["arm", "Arm", "angle, degrees"], ["wheel", "Wheels", "mean speed"]];
    $("#an-curves-sub").textContent = align ? "time 0 = the moment each run closed the gripper · thin: each run · thick: median" : "thin: each run · thick: median";
    if (!$("#an-chans").children.length) $("#an-chans").innerHTML = keys.map(([k, n, u]) => `<div class="chan"><span class="nm">${n}<small>${u}</small></span><canvas id="ac-${k}" height="120"></canvas><div class="vals" id="acv-${k}"></div></div>`).join("");
    const lo = align ? -10 : 0, hi = align ? 15 : Math.max(...[...A, ...B].map(x => x.T), 10);
    const grid = Array.from({ length: 120 }, (_, i) => lo + (i / 119) * (hi - lo));
    keys.forEach(([k]) => {
      const lines = [];
      const shift = (x, c) => (align ? c.map(([t, v]) => [t - x.closeT, v]).filter(([t]) => t >= lo && t <= hi) : c);
      if (each) [[A, css("--pink")], [B, css("--purple")]].forEach(([set, col]) => set.forEach(x => { if (!align || x.closeT != null) lines.push({ pts: shift(x, x.curves[k]), color: col, width: 1, alpha: .22 }); }));
      lines.push({ pts: medianCurve(A, k, align, grid), color: css("--pink"), width: 3.5 }, { pts: medianCurve(B, k, align, grid), color: css("--purple"), width: 3.5 });
      // chart() takes x from 0: shift the window so lo maps to the left edge
      chart($("#ac-" + k), { h: 120, xMax: hi - lo, zero: k === "wheel", lines: lines.map(l => ({ ...l, pts: l.pts.map(([t, v]) => [t - lo, v]) })), vlines: align ? [-lo] : [] });
      $("#acv-" + k).innerHTML = `<span>${align ? "−10 s … +15 s" : `0 … ${fmt(hi, 0)} s`}</span>${align ? "<span>line: gripper closes</span>" : ""}`;
    });
  }
  let anRows = [];
  function anRuns(A, B) {
    anRows = [...A.map(x => ["A", x]), ...B.map(x => ["B", x])];
    const res = x => (x.ok == null ? '<span class="muted">not judged</span>' : x.ok ? '<span class="pill2 ok">Picked up</span>' : '<span class="pill2 bad">Missed</span>');
    $("#an-runs").innerHTML = `<thead><tr><th></th><th>Run</th><th>Result</th><th class="num">Length</th><th class="num">Closes</th><th class="num">Lifts</th></tr></thead><tbody>` +
      anRows.map(([g, x]) => `<tr class="row" data-key="${x.key}"><td><span class="sw ${g.toLowerCase()}"></span></td><td><b>${esc(x.name)}</b>${x.pos ? ` <span class="muted mono" style="font-size:12px">spot ${x.pos}</span>` : ""}</td><td>${res(x)}</td>
        <td class="num">${fmt(x.T)} s</td><td class="num">${x.closeT == null ? "—" : fmt(x.closeT) + " s"}</td><td class="num">${x.liftT == null ? "—" : fmt(x.liftT) + " s"}</td></tr>`).join("") + "</tbody>";
    $$("#an-runs tr.row").forEach(tr => tr.onclick = () => { P.show("runs"); rSelect(tr.dataset.key); });
  }
  $("#an-csv").onclick = () => {
    const csv = ["group,run,kind,spot,result,length_s,gripper_closes_s,arm_lifts_s,steps_per_s"].concat(anRows.map(([g, x]) =>
      [g, x.name, x.kind === "r" ? "rollout" : "demo", x.pos ?? "", x.ok == null ? "" : x.ok ? "picked_up" : "missed", fmt(x.T, 2), x.closeT == null ? "" : fmt(x.closeT, 2), x.liftT == null ? "" : fmt(x.liftT, 2), fmt(x.hz, 2)].join(","))).join("\n");
    copyText(csv, $("#an-csv")); $("#an-msg").textContent = `${anRows.length} rows`;
  };
  function anLatency() {
    const T = (L.tests || []).filter(t => t.chunks.length);
    const groups = {};
    T.forEach(t => (groups[t.checkpoint] = groups[t.checkpoint] || []).push(...t.chunks.map(c => c.round_trip_ms)));
    const v2 = median(RUNS.map(r => r.m.med));
    const bars = Object.entries(groups).map(([k, v]) => [k + " (CPU)", median(v), v.length]).concat([["v2 on mps: gap between steps", v2, RUNS.reduce((a, r) => a + r.m.n, 0)]]);
    const cv = $("#an-lat"), dpr = devicePixelRatio || 1, w = cv.clientWidth, h = 200;
    if (!w) return;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const lmx = Math.log10(Math.max(...bars.map(b => b[1])) * 1.5), lmn = 1, X = v => 210 + ((Math.log10(v) - lmn) / (lmx - lmn)) * (w - 290);
    bars.forEach(([n, v, c], i) => {
      const y = 22 + i * 52;
      g.fillStyle = css("--navy"); g.font = "900 13px " + css("--font"); g.fillText(n, 4, y + 14);
      g.fillStyle = css("--navy-2"); g.font = "700 11px " + css("--font"); g.fillText(`${c} samples`, 4, y + 30);
      g.fillStyle = i === bars.length - 1 ? css("--s-arm") : v > 5000 ? css("--bad") : css("--purple");
      g.beginPath(); g.roundRect(210, y, Math.max(6, X(v) - 210), 26, 8); g.fill();
      g.fillStyle = css("--navy"); g.font = "800 13px " + css("--mono"); g.fillText(v >= 1000 ? fmt(v / 1000, 1) + " s" : Math.round(v) + " ms", X(v) + 8, y + 18);
    });
    const base = groups["lerobot/smolvla_base"];
    $("#an-lat-note").innerHTML = `<p class="muted" style="font-size:13px;font-weight:700;margin:6px 0 0">Log scale. ${base ? `smolvla_base on the laptop CPU needs ${fmt(median(base) / 1000, 1)} s for one chunk of 50 actions, which Neil uses up in 5 s at 10 steps per second: about ${fmt(median(base) / 5000, 1)}× too slow for real time.` : ""} The dummy server (no model) answered in a median ${fmt(median(groups["dummy server"] || [0]), 0)} ms; the dry-run guide starts it with <span class="mono">--dummy-latency 0.5</span>, so most of that is a deliberate wait. On 15 Oct, v2 on the laptop GPU (mps) kept a median of ${Math.round(v2)} ms between control steps, with longer pauses while a new chunk was on its way.</p>`;
  }

  // ================= JOBS: queue, suggestions, history =================
  const JTYPES = {
    record: { name: "Record demos", where: "laptop + gamepad", fields: [["spot", "Start spot", "select", ["1", "2", "3", "4", "5"], "1"], ["n", "Demos to record", "number", null, 10], ["speed", "Wheel speed", "number", null, 30]],
      cmd: f => `# branch vla-recording · drive Neil with the gamepad, ${f.n} demos from spot ${f.spot}\npython scripts/gamepad_drive.py --record --speed ${f.speed}\n# then turn the sessions into training episodes\npython scripts/session_to_episode.py logs/session_* --out episodes --task "pick up the cup"`,
      title: f => `Record ${f.n} demos from spot ${f.spot}` },
    label: { name: "Label with Claude", where: "laptop", fields: [["paths", "Folders or attempts", "text", null, "logs/"], ["frames", "Frames per camera", "number", null, 8], ["effort", "Effort", "select", ["low", "medium", "high"], "medium"], ["dry", "Dry run (contact sheets only, no API calls)", "check", null, false]],
      cmd: f => `# branch claude/project-thread-hph8vb · writes output/classifier/<date>_<time>/\npython scripts/classify_attempts.py ${f.paths} --task "pick up the cup" --frames ${f.frames} --effort ${f.effort}${f.dry ? " --dry-run" : ""}`,
      title: f => `Label ${f.paths} with Claude${f.dry ? " (dry run)" : ""}` },
    train: { name: "Fine-tune on Athena", where: "Athena GPU", fields: [["ds", "Dataset", "text", null, "pick_cup"], ["steps", "Training steps", "number", null, 20000], ["batch", "Batch size", "number", null, 64], ["test", "Short test first (200 steps, 2h_2g queue)", "check", null, false]],
      cmd: f => `# from the laptop: copy the dataset to Athena\nrsync -av data/${f.ds} your.name@athena.technion.ac.il:$VLA/data/\n# on Athena, in the jobs folder\n${f.test ? `sbatch --qos=2h_2g --time=00:30:00 train_neil.job 200 8 ${f.ds}` : `sbatch train_neil.job ${f.steps} ${f.batch} ${f.ds}`}\ntsqr -u $USER                      # PD = waiting, R = running\ntail -f neil_smolvla_JOBID.log     # Ctrl+C stops watching, not the job`,
      title: f => f.test ? `Test training on ${f.ds} (200 steps)` : `Fine-tune on ${f.ds}: ${Number(f.steps).toLocaleString("en-US")} steps` },
    eval: { name: "Evaluate on Neil", where: "laptop + Neil", fields: [["model", "Model", "select", ["handoff_pick_cup_pos2", "pick_cup_angle_182076", "pick_cup"], "handoff_pick_cup_pos2"], ["n", "Runs", "number", null, 10], ["seconds", "Seconds per run", "number", null, 30]],
      cmd: f => `# in inference_kit/ · stay next to Neil, Ctrl+C stops it\nfor i in $(seq 1 ${f.n}); do\n  python run_policy.py --policy ../models/${f.model}/pretrained_model --task "pick up the cup" --seconds ${f.seconds}\n  read -p "Reset the cup and Neil, then press Enter"\ndone\n# then let Claude judge the new runs\npython ../scripts/classify_attempts.py runs/`,
      title: f => `Evaluate ${f.model}: ${f.n} runs on Neil` },
    dry: { name: "Dry run on a recording", where: "laptop", fields: [["session", "Recorded session", "text", null, "logs/session_20261014_105424"], ["ckpt", "Checkpoint", "text", null, "models/handoff_pick_cup_pos2/pretrained_model"], ["spec", "Observation spec", "select", ["specs/pick_cup.json", "specs/pick_cup_pos2.json", "specs/pick_cup_angle.json", "specs/pick_cup_kit.json"], "specs/pick_cup_pos2.json"]],
      cmd: f => `# terminal 1: the policy server\npython policy_server/server.py --checkpoint ${f.ckpt} --device mps\n# terminal 2: replay a recording through it; nothing moves\npython scripts/run_policy.py --replay ${f.session} --spec ${f.spec} --mode async --seconds 30`,
      title: f => `Dry run ${f.ckpt.split("/")[1] || f.ckpt} on ${f.session.split("/").pop()}` },
  };
  let jType = "label", jForm = {};
  let queue = store.get("loopvla-jobs", []);
  const jSave = () => store.set("loopvla-jobs", queue);
  const STATUS = ["Queued", "Running", "Done", "Failed"];
  function jFields() {
    const t = JTYPES[jType];
    jForm = Object.fromEntries(t.fields.map(([k, , , , d]) => [k, jForm[k] ?? d]));
    $("#jb-types").innerHTML = Object.entries(JTYPES).map(([k, v]) => `<button class="chip${k === jType ? " on" : ""}" data-t="${k}">${v.name}</button>`).join("");
    $$("#jb-types .chip").forEach(c => c.onclick = () => { jType = c.dataset.t; jForm = {}; jFields(); });
    $("#jb-form").innerHTML = t.fields.map(([k, label, type, opts]) =>
      type === "select" ? `<label class="fld">${label}<select data-f="${k}">${opts.map(o => `<option${String(jForm[k]) === o ? " selected" : ""}>${o}</option>`).join("")}</select></label>`
      : type === "check" ? `<label style="display:flex;gap:8px;align-items:center;font-size:14px;font-weight:800;grid-column:1/-1"><input type="checkbox" data-f="${k}"${jForm[k] ? " checked" : ""}> ${label}</label>`
      : `<label class="fld">${label}<input type="${type}" data-f="${k}" value="${esc(jForm[k])}"></label>`).join("") + `<p class="muted" style="grid-column:1/-1;margin:0;font-size:13px;font-weight:800">Runs on: ${t.where}</p>`;
    $$("#jb-form [data-f]").forEach(el => el.oninput = () => { jForm[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value; jCmdShow(); });
    jCmdShow();
  }
  const jCmdShow = () => { $("#jb-cmd").textContent = JTYPES[jType].cmd(jForm); };
  function jAdd(type, form) {
    const t = JTYPES[type];
    queue.push({ id: Date.now().toString(36), type, title: t.title(form), cmd: t.cmd(form), status: "Queued", jobid: "", at: new Date().toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) });
    jSave(); jQueue();
  }
  $("#jb-add").onclick = () => { jAdd(jType, jForm); $("#jb-msg").textContent = "Added. Copy the command and run it, then set its status."; };
  $("#jb-copy").onclick = () => copyText($("#jb-cmd").textContent, $("#jb-copy"));
  $("#jb-script").onclick = () => {
    const q = queue.filter(j => j.status === "Queued");
    copyText(q.length ? q.map(j => `# ---- ${j.title}\n${j.cmd}`).join("\n\n") : "# nothing queued", $("#jb-script"));
  };
  $("#jb-clear").onclick = () => { queue = queue.filter(j => j.status !== "Done"); jSave(); jQueue(); };
  function jQueue() {
    $("#jb-count").textContent = `${queue.filter(j => j.status === "Queued").length} queued · ${queue.filter(j => j.status === "Running").length} running`;
    $("#jb-queue").innerHTML = queue.length ? queue.map((j, i) => `<div class="qitem s-${j.status.toLowerCase()}" data-i="${i}">
        <div class="qtop"><b>${esc(j.title)}</b><span class="muted mono" style="font-size:12px">${esc(JTYPES[j.type]?.name || j.type)} · added ${esc(j.at)}</span></div>
        <details><summary>Command</summary><div class="cmd">${esc(j.cmd)}</div></details>
        <div class="qbar"><select data-act="status">${STATUS.map(s2 => `<option${s2 === j.status ? " selected" : ""}>${s2}</option>`).join("")}</select>
          ${j.type === "train" ? `<input type="text" data-act="jobid" placeholder="Athena job id" value="${esc(j.jobid)}" style="width:130px">` : ""}
          <button class="btn2" data-act="copy">Copy</button><button class="btn2" data-act="up" ${i ? "" : "disabled"} aria-label="Move up">↑</button><button class="btn2" data-act="del">Remove</button></div></div>`).join("")
      : `<p class="muted" style="font-weight:800;margin:0">Nothing queued. Add a job on the left or take one of the suggestions above.</p>`;
    $$("#jb-queue .qitem").forEach(el => {
      const i = +el.dataset.i, j = queue[i];
      el.querySelector('[data-act="status"]').onchange = e => { j.status = e.target.value; jSave(); jQueue(); jbHist(); };
      el.querySelector('[data-act="jobid"]')?.addEventListener("change", e => { j.jobid = e.target.value.trim(); jSave(); jbHist(); });
      el.querySelector('[data-act="copy"]').onclick = e => copyText(j.cmd, e.target);
      el.querySelector('[data-act="up"]').onclick = () => { [queue[i - 1], queue[i]] = [queue[i], queue[i - 1]]; jSave(); jQueue(); };
      el.querySelector('[data-act="del"]').onclick = () => { queue.splice(i, 1); jSave(); jQueue(); };
    });
  }
  function jbSugg() {
    const unjudged = DEMOS.filter(d => !d.v).length, missed = RUNS.filter(r => r.outcome === "missed_cup").length;
    const S = P.S, toGo = Math.max(0, S.goal - S.demos);
    const items = [
      unjudged && ["label", { paths: '"all poistions 2/"', frames: 8, effort: "medium", dry: false }, `Label ${unjudged} demos Claude has not seen`, `Batch B (${unjudged} demos) has no verdicts, so none of it can go into the next training set yet.`],
      missed && ["eval", { model: "handoff_pick_cup_pos2", n: 10, seconds: 30 }, "Evaluate v2 from all five spots", `v2 missed ${missed} of ${RUNS.length} rollouts by driving past the cup. Five runs from one spot are too few to tell where it fails.`],
      MODELS[3].rate == null || !MODELS[3].real ? ["eval", { model: "pick_cup_angle_182076", n: 10, seconds: 30 }, "Test v3 on Neil", "v3 (pick_cup_angle_182076, job 182076) has never driven Neil. Measure it before it can replace v2."] : null,
      ["train", { ds: "pick_cup", steps: 20000, batch: 64, test: toGo > 0 }, toGo > 0 ? `Test the training job (${toGo} demos to go)` : `Fine-tune on ${S.demos} demos`, toGo > 0 ? `The next fine-tune starts at ${S.goal} good demos. A 200-step test now catches problems before then.` : `${S.demos} demos are ready: the threshold of ${S.goal} is reached.`],
    ].filter(Boolean);
    $("#jb-sugg").innerHTML = items.map(([t, f, title, why], i) => `<div class="sg"><span class="pill2 lab">${JTYPES[t].name}</span><b>${esc(title)}</b><p>${esc(why)}</p><button class="btn2 primary" data-sg="${i}">Add to queue</button></div>`).join("");
    $$("#jb-sugg [data-sg]").forEach(b => b.onclick = () => { const [t, f] = items[+b.dataset.sg]; jAdd(t, { ...Object.fromEntries(JTYPES[t].fields.map(x => [x[0], x[4]])), ...f }); b.textContent = "Added"; b.disabled = true; });
  }
  function jbHist() {
    const rows = [
      ["14 Oct 11:16–12:07", "Dry runs on recordings", "9 pipeline tests: dummy server and smolvla_base on CPU", "Neil-LabAI/logs/run_20261014_*", "Done"],
      ["14 Oct 13:08", "Label with Claude", `${L.summary.attempts} attempts · ${L.summary.successes} picked up · $${L.labels.reduce((a, l) => a + l.cost_usd, 0).toFixed(2)} · ${L.summary.model}`, "output/classifier/ (branch claude/project-thread-hph8vb)", "Done"],
      ["Athena 181436", "Fine-tune", "v1 pick_cup · 50 demos · 10,000 steps", "outputs/neil_181436/checkpoints/last/pretrained_model", "Done"],
      ["Athena 181719", "Fine-tune", "final loss 0.09", "outputs/neil_181719/", "Done"],
      ["Athena 182076", "Fine-tune", "v3 pick_cup_angle_182076 (angle actions)", "outputs/neil_182076/", "Done"],
      ["15 Oct 09:47–09:59", "Evaluate on Neil", `v2 · ${L.rollouts.length} runs · ${RUNS.filter(r => r.outcome === "grasped").length} grasped · ${RUNS.filter(r => r.outcome === "missed_cup").length} missed · ${L.rollouts.length - RUNS.length} stopped`, "dashboard_sample_data/vla_rollouts/", "Done"],
      ...queue.filter(j => j.status !== "Queued").map(j => [j.at, JTYPES[j.type]?.name || j.type, j.title + (j.jobid ? ` · job ${j.jobid}` : ""), "queued from this dashboard", j.status]),
    ];
    const pill = st => st === "Done" ? '<span class="pill2 ok">Done</span>' : st === "Failed" ? '<span class="pill2 bad">Failed</span>' : `<span class="pill2 ai"><span class="dot"></span>${st}</span>`;
    $("#jb-hist").innerHTML = `<thead><tr><th>When</th><th>Job</th><th>What</th><th>Output</th><th>Status</th></tr></thead><tbody>` +
      rows.map(r => `<tr><td class="mono" style="white-space:nowrap">${esc(r[0])}</td><td><b>${esc(r[1])}</b></td><td>${esc(r[2])}</td><td class="mono" style="font-size:12px">${esc(r[3])}</td><td>${pill(r[4])}</td></tr>`).join("") + "</tbody>";
  }
  function jbRender() { jFields(); jQueue(); jbSugg(); jbHist(); }

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
      if (v === "analysis") requestAnimationFrame(anRender);
      if (v === "jobs") jbRender();
    },
  };
  let sig = "";
  setInterval(() => {   // keep Models in step with the overnight upgrade
    const s = `${P.S.version}|${$("#tLbl")?.textContent}|${P.S.demos}`;
    if (s !== sig && $("#v-models").classList.contains("on")) { sig = s; mRender(); }
  }, 1000);
  (function loop() { oFrame(); rDraw(); requestAnimationFrame(loop); })();
  addEventListener("resize", () => { if ($("#v-labels").classList.contains("on")) lHist(); if ($("#v-runs").classList.contains("on") && cur) rSide(); if ($("#v-analysis").classList.contains("on")) anRender(); });
  oLoad(0); oRender();
  const cv = $(".tab.on")?.dataset.view; if (cv && P.LAB_VIEWS.includes(cv)) window.LAB.shown(cv);
})();
