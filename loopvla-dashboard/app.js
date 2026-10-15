/* LoopVLA. Plain JS, no build step. */
(() => {
  const D = window.LOOP_DATA;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pad = (n, w) => String(n).padStart(w, "0");

  // ---------- Demos: when does Neil drive and grab? (from the motor log) ----------
  function phases(e) {
    const n = e.sig.grip.length - 1;
    const drive = e.sig.left.findIndex((l, i) => Math.abs(l || 0) + Math.abs(e.sig.right[i] || 0) > 5);
    const open = e.sig.grip.findIndex(g => g !== null && g > -35);
    const grip = open < 0 ? -1 : e.sig.grip.findIndex((g, i) => i > open && g !== null && g < -45);
    return { d: drive >= 0 ? drive / n : 0.15, g: grip >= 0 ? grip / n : 0.75 };
  }
  const VERDICT = {};
  for (const l of (window.LAB_DATA?.labels || [])) if (l.demo) VERDICT[l.demo] = l;
  const EPS = D.episodes.map((e, i) => ({ ...e, no: i + 1, ph: phases(e), v: VERDICT[e.id] || null }));
  const SAY = ["Finding the cup", "Driving to the cup", "Grabbing the cup", "Got it!"];
  function phaseAt(ph, f) {   // f: 0..1 through the demo
    if (f < ph.d) return 0;
    if (f < ph.g - 0.03) return 1;
    if (f < Math.min(0.97, ph.g + 0.16)) return 2;
    return 3;
  }

  // ---------- State ----------
  const S = { demos: 97, goal: 100, rate: 60, version: 3, rates: [0, 40, 60], measured: [false, false, true, false], storyOn: false };

  // ---------- Pages ----------
  const VIEWS = ["loop", "flow", "data", "brain", "impact"];
  const LAB_VIEWS = ["ops", "runs", "labels", "models"];
  const pill = $("#tabPill");
  function movePill() { const on = $(".tab.on"); pill.style.left = on.offsetLeft + "px"; pill.style.width = on.offsetWidth + "px"; }
  function show(v) {
    const lab = LAB_VIEWS.includes(v);
    if (lab && S.storyOn) stopStory();
    document.body.classList.toggle("lab", lab);
    $$("#modeSwitch button").forEach(b => b.classList.toggle("on", b.dataset.mode === (lab ? "lab" : "pitch")));
    $$(".tab").forEach(t => t.classList.toggle("on", t.dataset.view === v));
    $$(".view").forEach(s => s.classList.toggle("on", s.id === "v-" + v));
    movePill();
    if (v === "loop") requestAnimationFrame(layoutPath);
    if (v === "flow") requestAnimationFrame(layoutBack);
    if (v === "data") renderGrid();
    if (v === "brain") drawChart(true);
    requestAnimationFrame(moveModeKnob);
    window.LAB?.shown(v);
  }
  const lastView = { pitch: "loop", lab: "ops" };
  function moveModeKnob() {
    const on = $("#modeSwitch button.on"), k = $("#modeKnob");
    if (on) { k.style.left = on.offsetLeft + "px"; k.style.width = on.offsetWidth + "px"; }
  }
  $$("#modeSwitch button").forEach(b => b.onclick = () => {
    const cur = $(".tab.on")?.dataset.view;
    if (cur) lastView[LAB_VIEWS.includes(cur) ? "lab" : "pitch"] = cur;
    show(lastView[b.dataset.mode]);
  });
  $$(".tab").forEach(t => t.onclick = () => show(t.dataset.view));
  addEventListener("resize", () => { movePill(); layoutPath(); layoutBack(); });
  requestAnimationFrame(movePill);

  // ---------- Light that follows the pointer ----------
  let pm = null;
  addEventListener("pointermove", e => { pm = e; });
  (function light() {
    if (pm) {
      for (const g of $$(".view.on .lg, .top .lg, .modal.on, .modal.on .lg")) {
        const r = g.getBoundingClientRect();
        g.style.setProperty("--mx", pm.clientX - r.left + "px");
        g.style.setProperty("--my", pm.clientY - r.top + "px");
      }
      pm = null;
    }
    requestAnimationFrame(light);
  })();

  // ---------- Loop path around the live video ----------
  const stage = $("#stage"), spark = $("#spark");
  let pathLen = 0;
  function layoutPath() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w) return;
    const i = 29, r = 56, x0 = i, y0 = i, x1 = w - i, y1 = h - i;
    const d = `M${x0 + r},${y0} H${x1 - r} A${r},${r} 0 0 1 ${x1},${y0 + r} V${y1 - r} A${r},${r} 0 0 1 ${x1 - r},${y1} H${x0 + r} A${r},${r} 0 0 1 ${x0},${y1 - r} V${y0 + r} A${r},${r} 0 0 1 ${x0 + r},${y0} Z`;
    $("#pathSvg").setAttribute("viewBox", `0 0 ${w} ${h}`);
    $("#trackPath").setAttribute("d", d); $("#flowPath").setAttribute("d", d);
    pathLen = $("#trackPath").getTotalLength();
  }
  let sparkAt = 0, sparkSpeed = 1;
  (function run() {
    if (pathLen) {
      sparkAt = (sparkAt + 2.2 * sparkSpeed) % pathLen;
      const p = $("#trackPath").getPointAtLength(sparkAt);
      spark.setAttribute("cx", p.x); spark.setAttribute("cy", p.y);
    }
    requestAnimationFrame(run);
  })();
  function step(name) { $$(".step").forEach(s => s.classList.toggle("on", s.dataset.s === name)); }

  // ---------- Live demo ----------
  const LIVE = D.live.map(l => ({ ...l, ph: phases(EPS.find(e => e.id === l.id)) }));
  LIVE.forEach((l, k) => { for (let j = 0; j < l.n; j++) new Image().src = `assets/live/${k}/${pad(j, 3)}.jpg`; });
  function place(el, b, grow) {
    if (!b) { el.style.opacity = 0; return; }
    const [x0, y0, x1, y1] = b, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, w = (x1 - x0) * grow, h = (y1 - y0) * grow;
    Object.assign(el.style, { opacity: 1, left: (cx - w / 2) * 100 + "%", top: (cy - h / 2) * 100 + "%", width: w * 100 + "%", height: h * 100 + "%" });
  }
  let lk = 0, lj = 0, hold = 0, mode = "play";
  function liveTick() {
    if (mode !== "play") return;
    const l = LIVE[lk];
    $("#liveImg").src = `assets/live/${lk}/${pad(lj, 3)}.jpg`;
    const b = l.boxes[lj] || {};
    place($("#cupBox"), b.cup, 1.3);
    place($("#botBox"), b.bot, 2.0);
    const p = phaseAt(l.ph, lj / (l.n - 1));
    $("#say").textContent = SAY[p];
    step(p === 0 ? "watch" : "record");
    if (++lj >= l.n) finishDemo();
  }
  async function finishDemo() {
    mode = "label";
    step("label");
    $("#say").textContent = "AI: this is a good demo";
    $("#stamp").classList.add("on");
    addDemo();
    await sleep(1800);
    $("#stamp").classList.remove("on");
    step("train");
    $("#say").textContent = S.demos >= S.goal ? "Training a smarter brain" : "Saved for tonight's training";
    if (S.demos >= S.goal && !S.storyOn) upgrade();
    await sleep(1500);
    lj = 0; lk = (lk + 1) % LIVE.length; mode = "play";
  }
  setInterval(liveTick, 200);   // the frames were sampled at 5 per second

  // ---------- Numbers ----------
  function count(el, to, suffix = "", ms = 900) {
    const from = el._v ?? (parseFloat(el.textContent) || 0), t0 = performance.now();
    el._v = to; cancelAnimationFrame(el._raf);
    const tick = () => {
      const k = Math.max(0, Math.min(1, (performance.now() - t0) / ms)), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(from + (to - from) * e) + suffix;
      if (k < 1) el._raf = requestAnimationFrame(tick);
    };
    tick();
  }
  function refresh() {
    count($("#nDemos"), S.demos); count($("#nData"), S.demos);
    $("#nJudged").textContent = EPS.filter(e => e.v).length;
    const st = $("#statDemos"); st.classList.remove("bump"); void st.offsetWidth; st.classList.add("bump");
    $("#tVal").textContent = `${S.demos} / ${S.goal} demos`;
    $("#tBar").style.width = Math.min(100, (S.demos / S.goal) * 100) + "%";
  }
  function addDemo() {
    const src = EPS[EPS.findIndex(e => e.id === LIVE[lk].id)];
    S.demos++;
    EPS.push({ ...src, no: S.demos, fresh: true });
    refresh();
    if ($("#v-data").classList.contains("on")) renderGrid();
  }
  async function upgrade() {
    $("#tLbl").textContent = "Training now";
    for (let p = 0; p <= 100; p += 5) { $("#tBar").style.width = p + "%"; $("#tVal").textContent = p + "%"; await sleep(90); }
    S.version = 4; S.rates = [0, 40, 60, 81]; S.rate = 81;
    count($("#rate"), 81, "%", 1400);
    drawChart(false);
    S.goal = 200;
    $("#tLbl").textContent = "Next upgrade";
    refresh();
  }

  // ---------- Data wall ----------
  let pos = 0;
  $$("#chips .chip").forEach(c => c.onclick = () => {
    pos = +c.dataset.pos;
    $$("#chips .chip").forEach(x => x.classList.toggle("on", x === c));
    renderGrid();
  });
  function renderGrid() {
    const g = $("#grid"); g.innerHTML = "";
    EPS.filter(e => !pos || e.pos === pos).slice().reverse().forEach((e, n) => {
      const c = document.createElement("div");
      c.className = "card";
      c.style.animationDelay = Math.min(n, 30) * 22 + "ms";
      c.innerHTML = `<img loading="lazy" src="assets/eps/${e.id}/t05.jpg" alt="">
        ${e.v ? `<div class="ok${e.v.success ? "" : " no"}"><svg><use href="#i-${e.v.success ? "check" : "x"}"/></svg></div>` : `<div class="ok wait" title="Not judged yet">…</div>`}
        <div class="tag">Demo ${e.no}</div><div class="bar"><b></b></div>`;
      const im = $("img", c), bar = $(".bar b", c);
      c.onpointermove = ev => {
        const r = c.getBoundingClientRect(), k = Math.max(0, Math.min(9, Math.floor(((ev.clientX - r.left) / r.width) * 10)));
        im.src = `assets/eps/${e.id}/t${pad(k, 2)}.jpg`; bar.style.width = (k / 9) * 100 + "%";
      };
      c.onpointerleave = () => { im.src = `assets/eps/${e.id}/t05.jpg`; };
      c.onclick = () => openDemo(e);
      g.appendChild(c);
    });
  }

  // ---------- Demo viewer ----------
  let mTimer = null;
  function openDemo(e) {
    $("#mTitle").textContent = e.v ? `Demo ${e.no} · ${e.v.success ? "picked up" : "missed"} · ${Math.round(e.v.confidence * 100)}% sure` : `Demo ${e.no} · not judged yet`;
    $("#modal").classList.toggle("unjudged", !e.v);
    $("#mNotes").innerHTML = e.v ? `<b>Claude's notes</b>${e.v.reason.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))}` : "<b>Claude's notes</b>Waiting in the queue. Claude has not watched this demo yet.";
    let k = 0;
    const frame = () => {
      $("#mTop").src = `assets/eps/${e.id}/t${pad(k, 2)}.jpg`;
      $("#mEye").src = `assets/eps/${e.id}/f${pad(k, 2)}.jpg`;
      $("#mSay").textContent = SAY[phaseAt(e.ph, k / 9)];
      k = (k + 1) % 10;
    };
    frame(); clearInterval(mTimer); mTimer = setInterval(frame, 700);
    $("#veil").classList.add("on"); $("#modal").classList.add("on");
  }
  function closeDemo() { $("#veil").classList.remove("on"); $("#modal").classList.remove("on"); clearInterval(mTimer); }
  $("#veil").onclick = closeDemo; $("#mx").onclick = closeDemo;

  // ---------- Brain chart ----------
  function drawChart(animate) {
    const W = 800, H = 560, L = 70, R = 730, T = 70, B = 470;
    const n = 4, xs = i => L + (i * (R - L)) / (n - 1), ys = v => B - (v / 100) * (B - T);
    const pts = S.rates.map((v, i) => [xs(i), ys(v)]);
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 1; i < pts.length; i++) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], m = (x1 - x0) / 2;
      d += ` C${x0 + m},${y0} ${x1 - m},${y1} ${x1},${y1}`;
    }
    const last = pts[pts.length - 1];
    const names = ["Base", "Version 1", "Version 2", S.version >= 4 ? "Version 3" : "Tonight"];
    let s = `<defs>
      <linearGradient id="cl" x1="0" x2="1"><stop offset="0" stop-color="#ff9fd0"/><stop offset=".6" stop-color="#e0218a"/><stop offset="1" stop-color="#6c6be0"/></linearGradient>
      <linearGradient id="ca" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ff5fae" stop-opacity=".35"/><stop offset="1" stop-color="#ff5fae" stop-opacity="0"/></linearGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="8"/></filter></defs>`;
    s += `<path d="${d} L${last[0]},${B} L${pts[0][0]},${B} Z" fill="url(#ca)"/>`;
    s += `<path d="${d}" fill="none" stroke="url(#cl)" stroke-width="14" stroke-linecap="round" opacity=".45" filter="url(#glow)"/>`;
    s += `<path d="${d}" fill="none" stroke="url(#cl)" stroke-width="8" stroke-linecap="round" pathLength="1"
      ${animate ? `stroke-dasharray="1" stroke-dashoffset="1"><animate attributeName="stroke-dashoffset" from="1" to="0" dur="1.3s" fill="freeze" calcMode="spline" keySplines=".2 .8 .3 1" keyTimes="0;1"/></path>` : "/>"}`;
    if (S.version < 4) s += `<circle cx="${xs(3)}" cy="${ys(81)}" r="26" fill="none" stroke="#6c6be0" stroke-width="4" stroke-dasharray="7 8"/>
      <text x="${xs(3)}" y="${ys(81) - 46}" text-anchor="middle" font-size="40" font-weight="900" fill="#6c6be0" opacity=".55">?</text>`;
    pts.forEach(([x, y], i) => {
      const top = i === pts.length - 1;
      s += `<circle cx="${x}" cy="${y}" r="${top ? 26 : 18}" fill="#fff" stroke="${top ? "#e0218a" : "#ff9fd0"}" stroke-width="${top ? 9 : 7}"/>
        <text x="${x}" y="${y - (top ? 50 : 40)}" text-anchor="middle" font-size="${top ? 54 : 38}" font-weight="900" letter-spacing="-2" fill="${top ? "#e0218a" : "#1b2a59"}">${S.rates[i]}%</text>
        ${S.measured[i] ? `<text x="${x}" y="${y + (top ? 62 : 52)}" text-anchor="middle" font-size="19" font-weight="900" fill="#5b8030">measured · 3 of 5</text>` : ""}`;
    });
    names.forEach((t, i) => s += `<text x="${xs(i)}" y="${B + 62}" text-anchor="middle" font-size="24" font-weight="800" fill="${i === 3 && S.version < 4 ? "#6c6be0" : "#56608a"}">${t}</text>`);
    $("#chart").innerHTML = s;
  }

  // ---------- Workflow: today vs LoopVLA ----------
  let fMode = "today", fStep = 0;
  const TXT = {
    today: ["Start over by hand. Again and again.", "The log says <em>yes</em>. The robot says <em>no</em>."],
    loop: ["AI collects the data the robot is missing", "The robot gets the data it needs. <em>Until it learns.</em>"],
  };
  function flowMode(m) {
    fMode = m; fStep = 0;
    $("#v-flow").classList.toggle("loop-mode", m === "loop");
    $$("#flowSwitch button").forEach(b => b.classList.toggle("on", b.dataset.m === m));
    const on = $("#flowSwitch button.on"), k = $("#knob");
    k.style.left = on.offsetLeft + "px"; k.style.width = on.offsetWidth + "px";
    $("#backTxt").textContent = TXT[m][0];
    const v = $("#verdict"); v.classList.add("dim");
    setTimeout(() => { v.innerHTML = TXT[m][1]; v.classList.remove("dim"); }, 300);
  }
  $$("#flowSwitch button").forEach(b => b.onclick = () => flowMode(b.dataset.m));
  function layoutBack() {
    const wrap = $("#flowWrap"), bl = $$(".blk"), W = wrap.clientWidth, H = wrap.clientHeight;
    if (!W || !bl.length) return;
    const r0 = wrap.getBoundingClientRect(), a = bl[5].getBoundingClientRect(), b = bl[1].getBoundingClientRect();
    const x1 = a.left - r0.left + a.width / 2, x2 = b.left - r0.left + b.width / 2, y = a.bottom - r0.top + 14, low = H - 34;
    $("#backArrow").setAttribute("viewBox", `0 0 ${W} ${H}`);
    $("#backPath").setAttribute("d", `M${x1},${y} C${x1},${low} ${x1},${low} ${x1 - 60},${low} H${x2 + 60} C${x2},${low} ${x2},${low} ${x2},${y + 16}`);
    $("#backHead").setAttribute("points", `${x2 - 13},${y + 22} ${x2 + 13},${y + 22} ${x2},${y + 2}`);
    const k = $("#knob"), on = $("#flowSwitch button.on");
    k.style.left = on.offsetLeft + "px"; k.style.width = on.offsetWidth + "px";
  }
  setInterval(() => {   // a highlight walks through the blocks, then loops back
    if (!$("#v-flow").classList.contains("on")) return;
    const bl = $$(".blk");
    bl.forEach(b => b.classList.remove("act", "shake"));
    const i = fStep % 7;
    if (i < 6) bl[i].classList.add("act");
    if (i === 5 && fMode === "today") bl[5].classList.add("shake");
    fStep = i === 6 ? 1 : fStep + 1;   // the loop goes back to "collect demos"
  }, 700);

  // ---------- Story mode: under one minute ----------
  let run = 0;
  async function beat(text, ms, fn) {
    if (!S.storyOn) throw 0;
    $("#capT").textContent = text; $("#caption").classList.add("on");
    fn && fn();
    const p = $("#capP"); p.style.transition = "none"; p.style.width = "0"; void p.offsetWidth;
    p.style.transition = `width ${ms}ms linear`; p.style.width = "100%";
    await sleep(ms);
    if (!S.storyOn) throw 0;
  }
  async function story() {
    const id = ++run;
    try {
      await beat("Robots learn from examples. Today, people make them by hand.", 5500, () => show("loop"));
      await beat("With LoopVLA, the robot practices alone. AI labels every try.", 5500, () => { sparkSpeed = 2.5; });
      await beat("Today, the training log says it worked. The robot says no.", 6000, () => { show("flow"); flowMode("today"); });
      await beat("LoopVLA gives these steps to AI agents, and closes the loop.", 6500, () => flowMode("loop"));
      await beat(`${S.demos} demos. Not one filmed by hand.`, 5000, () => { closeDemo(); show("data"); });
      await beat("Each demo comes with its own AI notes.", 5000, () => openDemo(EPS.find(e => e.v) || EPS[0]));
      await beat("At 100 demos, the robot trains itself overnight.", 5500, () => {
        closeDemo(); show("brain");
        S.demos = Math.max(S.demos, S.goal); refresh(); upgrade();
      });
      await beat("One week of work becomes one night.", 5000, () => show("impact"));
      await beat("LoopVLA. Your team builds skills, not datasets.", 5500);
    } catch (_) { /* stopped */ }
    if (id === run) stopStory();
  }
  function startStory() {
    S.storyOn = true; document.body.classList.add("story");
    const b = $("#playBtn"); b.classList.add("on"); $("use", b).setAttribute("href", "#i-pause"); $("span", b).textContent = "Stop";
    story();
  }
  function stopStory() {
    S.storyOn = false; run++; sparkSpeed = 1; document.body.classList.remove("story");
    $("#caption").classList.remove("on"); closeDemo();
    const b = $("#playBtn"); b.classList.remove("on"); $("use", b).setAttribute("href", "#i-play"); $("span", b).textContent = "Play story";
  }
  $("#playBtn").onclick = () => S.storyOn ? stopStory() : startStory();

  addEventListener("keydown", e => {
    if (e.key === "Escape") { closeDemo(); if (S.storyOn) stopStory(); }
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    if ("12345".includes(e.key) && e.key.length === 1) show(VIEWS[+e.key - 1]);
    if ("6789".includes(e.key) && e.key.length === 1) show(LAB_VIEWS[+e.key - 6]);
    if (e.code === "Space" && !document.body.classList.contains("lab")) { e.preventDefault(); S.storyOn ? stopStory() : startStory(); }
  });

  window.LOOP = { S, EPS, show, refresh, upgrade, openDemo, LAB_VIEWS };

  // ---------- Start ----------
  refresh(); layoutPath(); drawChart(false);
  const h = location.hash.slice(1);
  if (VIEWS.includes(h) || LAB_VIEWS.includes(h)) show(h);
  if (h === "flow-loop") { show("flow"); setTimeout(() => flowMode("loop"), 50); }
  const q = new URLSearchParams(location.search);
  if (q.has("demo")) { show("data"); openDemo(EPS[+q.get("demo")]); }
  if (q.has("story")) startStory();
})();
