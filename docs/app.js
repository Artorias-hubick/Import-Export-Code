/* Import/Export Hub — графіки, фільтри, аналітика. Дані: window.DATA з data.js (build_site.py). */
(() => {
  "use strict";
  const D = window.DATA;
  if (!D) { document.querySelector("main").innerHTML = '<p class="empty">Немає data.js</p>'; return; }

  const CONFIG = {
    // GitHub Actions на сервері з ботами (self-hosted runner): Run workflow → завантаження всіх цін
    updateUrl: "https://github.com/Artorias-hubick/kt_bot/actions/workflows/update-prices.yml",
  };
  const ZONES = [
    { id: "UA", name: "Україна", c: "--s1" }, { id: "SK", name: "Словаччина", c: "--s2" },
    { id: "PL", name: "Польща", c: "--s3" }, { id: "HU", name: "Угорщина", c: "--s4" },
    { id: "RO", name: "Румунія", c: "--s5" }, { id: "MD", name: "Молдова", c: "--s6" },
  ];
  const ZONE = Object.fromEntries(ZONES.map(z => [z.id, z]));
  const NEIGH = ZONES.slice(1);
  const HOURS = [...Array(24).keys()];
  const HOUR_LABELS = HOURS.map(h => String(h + 1));
  const PEAK = h => h >= 8 && h <= 19; // індекси 8..19 = години 9..20 CET
  const HOURSEL = { all: () => true, peak: PEAK, off: h => !PEAK(h) };

  // ---------- утиліти
  const $ = id => document.getElementById(id);
  const iso = d => d.toISOString().slice(0, 10);
  const addDays = (s, n) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return iso(d); };
  const dm = s => `${s.slice(8)}.${s.slice(5, 7)}`;
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = (v, p = 1) => v == null || !isFinite(v) ? "—" :
    v.toLocaleString("uk-UA", { minimumFractionDigits: p, maximumFractionDigits: p });
  const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : null;
  const std = a => { const m = mean(a); return a.length > 1 ? Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)) : null; };
  const pct = (a, b) => a == null || b == null || !b ? null : (a - b) / Math.abs(b) * 100;
  const pill = (p, digits = 1) => p == null ? "—" :
    `<span class="pill ${p > 0 ? "up" : p < 0 ? "down" : ""}">${p > 0 ? "▲ +" : p < 0 ? "▼ " : ""}${fmt(p, digits)}%</span>`;
  const colored = (v, p = 2) => `<td class="${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "+" : ""}${fmt(v, p)}</td>`;
  const swatch = z => `<i style="background:var(${z.c})"></i>`;
  const store = {
    get: (k, def) => { try { const v = localStorage.getItem(k); return v == null ? def : JSON.parse(v); } catch (e) { return def; } },
    set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* приватне вікно */ } },
  };

  // ---------- дані
  const allDates = [...new Set(Object.values(D.rdn).flatMap(s => Object.keys(s)))].sort();
  const firstDate = allDates[0], lastDate = allDates[allDates.length - 1];
  const fxDates = Object.keys(D.fx).sort();
  const fxCache = {};
  function fx(d) {
    if (d in fxCache) return fxCache[d];
    let lo = 0, hi = fxDates.length - 1, r = fxDates[0];
    while (lo <= hi) { const m = (lo + hi) >> 1; if (fxDates[m] <= d) { r = fxDates[m]; lo = m + 1; } else hi = m - 1; }
    return (fxCache[d] = D.fx[r]);
  }

  const saved = store.get("hub-view", {});
  const state = {
    from: addDays(lastDate, -29), to: lastDate, preset: "30",
    agg: saved.agg || "day", hours: saved.hours || "all", cur: saved.cur || "EUR",
    zones: new Set(ZONES.map(z => z.id)), day: lastDate, arbDay: lastDate,
  };

  /** Ціна РДН зони z за добу d і годину h (0..23) у вибраній валюті. */
  function price(z, d, h) {
    const row = D.rdn[z][d]; const v = row && row[h];
    if (v == null) return null;
    const uah = z === "UA";
    if (state.cur === "EUR") return uah ? v / fx(d) : v;
    return uah ? v : v * fx(d);
  }
  /** Ціна перетину k ("UA-PL"); null — немає потужності або даних. */
  function cross(k, d, h) {
    const row = D.cross[k] && D.cross[k][d]; const v = row && row[h];
    return v == null ? null : state.cur === "EUR" ? v : v * fx(d);
  }
  const crossKey = (a, b) => D.cross[`${a}-${b}`] ? `${a}-${b}` : null;
  const unit = () => state.cur === "EUR" ? "EUR/МВт·год" : "грн/МВт·год";
  const money = () => state.cur === "EUR" ? "€" : "грн";
  const datesIn = (a, b) => allDates.filter(d => d >= a && d <= b);

  function bucketOf(d, h, single) {
    if (state.agg === "hour") return single ? String(h + 1) : `${dm(d)} ${String(h + 1).padStart(2, "0")}`;
    return state.agg === "day" ? d : state.agg === "month" ? d.slice(0, 7) : d.slice(0, 4);
  }
  function series(getter, dates) {
    const sel = HOURSEL[state.hours], acc = new Map(), single = dates.length === 1;
    for (const d of dates) for (const h of HOURS) {
      if (!sel(h)) continue;
      const b = bucketOf(d, h, single); if (!acc.has(b)) acc.set(b, []);
      const v = getter(d, h); if (v != null) acc.get(b).push(v);
    }
    return { labels: [...acc.keys()], values: [...acc.values()].map(mean) };
  }

  // ---------- графіки
  const charts = {};
  /**
   * opts.allTicks — показати всі підписи осі X (1..24 для погодинних графіків).
   * opts.type — "line" | "bar"; для bar кожен стовпчик може мати свій колір (set.colors).
   */
  function drawChart(id, labels, sets, opts = {}) {
    const muted = css("--muted"), type = opts.type || "line";
    const data = {
      labels, datasets: sets.map(s => type === "bar" ? {
        label: s.label, data: s.data, backgroundColor: s.colors || css(s.c), borderRadius: 4, borderSkipped: "start",
        maxBarThickness: 22, categoryPercentage: .8, barPercentage: .9,
      } : {
        label: s.label, data: s.data, borderColor: css(s.c), backgroundColor: css(s.c), borderWidth: 2,
        pointRadius: labels.length <= 48 ? 3 : 0, pointHoverRadius: 5, tension: .2, spanGaps: false,
        pointBorderColor: css("--surface"), pointBorderWidth: 1.5,
      }),
    };
    const horiz = !!opts.horizontal; // горизонтальні стовпчики: години 1..24 по вертикалі (вузька панель)
    const options = {
      indexAxis: horiz ? "y" : "x",
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false, axis: horiz ? "y" : "x" },
      plugins: {
        legend: { display: sets.length > 1 && opts.legend !== false,
          labels: { color: css("--text-2"), boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "rectRounded",
            font: { family: "Roboto", size: 12 } } },
        tooltip: { backgroundColor: css("--container-high"), titleColor: css("--text"), bodyColor: css("--text"),
          borderColor: css("--outline-variant"), borderWidth: 1, padding: 10, cornerRadius: 8,
          callbacks: { title: it => opts.titlePrefix ? `${opts.titlePrefix} ${it[0].label}` : it[0].label,
            label: c => ` ${c.dataset.label}: ${fmt(horiz ? c.parsed.x : c.parsed.y, 2)}` } },
      },
    };
    const catAxis = { ticks: { color: muted, maxRotation: 0, autoSkip: !opts.allTicks, maxTicksLimit: opts.allTicks ? undefined : 10,
        font: { family: "Roboto", size: 11 } },
      grid: { display: false }, border: { color: css("--outline-variant") },
      title: opts.xTitle ? { display: true, text: opts.xTitle, color: muted, font: { size: 11 } } : undefined };
    const valAxis = { ticks: { color: muted, callback: v => fmt(v, 0), font: { family: "Roboto", size: 11 } },
      grid: { color: css("--grid") }, border: { display: false },
      title: { display: true, text: opts.unit || unit(), color: muted, font: { size: 11 } } };
    options.scales = horiz ? { y: catAxis, x: valAxis } : { x: catAxis, y: valAxis };
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart($(id), { type, data, options });
  }

  // ---------- елементи керування
  function segmented(boxId, items, isOn, onPick) {
    const box = $(boxId);
    items.forEach(([v, label]) => {
      const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.dataset.v = v;
      b.addEventListener("click", () => onPick(v));
      box.appendChild(b);
    });
    return () => box.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(isOn(b.dataset.v))));
  }
  const PRESETS = [["1", "День"], ["7", "7 дн"], ["30", "30 дн"], ["90", "90 дн"], ["ytd", "З поч. року"], ["365", "Рік"], ["all", "Усе"]];
  const syncers = [
    segmented("presets", PRESETS, v => v === state.preset, v => {
      state.to = lastDate;
      state.from = v === "all" ? firstDate : v === "ytd" ? lastDate.slice(0, 4) + "-01-01" : addDays(lastDate, 1 - +v);
      if (v === "1") state.agg = "hour";
      else if (state.agg === "hour" && +v > 31) state.agg = "day";
      state.preset = v; render();
    }),
    segmented("aggs", [["hour", "Година"], ["day", "День"], ["month", "Місяць"], ["year", "Рік"]], v => v === state.agg,
      v => { state.agg = v; render(); }),
    segmented("hours", [["all", "Усі"], ["peak", "Пік"], ["off", "Поза піком"]], v => v === state.hours,
      v => { state.hours = v; render(); }),
    segmented("cur", [["EUR", "EUR"], ["UAH", "грн"]], v => v === state.cur, v => { state.cur = v; render(); }),
  ];
  ZONES.forEach(z => {
    const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.dataset.z = z.id;
    b.innerHTML = swatch(z); b.append(z.name);
    b.addEventListener("click", () => { state.zones.has(z.id) ? state.zones.delete(z.id) : state.zones.add(z.id); render(); });
    $("zones").appendChild(b);
  });
  const fromEl = $("from"), toEl = $("to");
  [fromEl, toEl, $("day"), $("arbDay")].forEach(el => { el.min = firstDate; el.max = lastDate; });
  fromEl.addEventListener("change", () => { if (fromEl.value) { state.from = fromEl.value; state.preset = null; render(); } });
  toEl.addEventListener("change", () => { if (toEl.value) { state.to = toEl.value; state.preset = null; render(); } });

  /** Кроки ◀ ▶ для поля дати, що зберігає значення в state[key]. */
  function dayStepper(inputId, prevId, nextId, key) {
    const shift = n => { const v = addDays(state[key], n); if (v >= firstDate && v <= lastDate) { state[key] = v; render(); } };
    $(prevId).addEventListener("click", () => shift(-1));
    $(nextId).addEventListener("click", () => shift(1));
    $(inputId).addEventListener("change", e => { if (e.target.value) { state[key] = e.target.value; render(); } });
  }
  dayStepper("day", "dayPrev", "dayNext", "day");
  dayStepper("arbDay", "arbPrev", "arbNext", "arbDay");
  [$("arbA"), $("arbB")].forEach((sel, i) => {
    ZONES.forEach(z => sel.add(new Option(z.name, z.id)));
    sel.value = i ? "MD" : "UA";
    sel.addEventListener("change", render);
  });

  // ---------- тема
  const isDark = () => document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  function syncThemeIcon() { $("themeIcon").textContent = isDark() ? "light_mode" : "dark_mode"; }
  $("theme").addEventListener("click", () => {
    const t = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem("hub-theme", t); } catch (e) { /* без збереження */ }
    syncThemeIcon(); render();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { syncThemeIcon(); render(); });

  // ---------- кнопка «Оновити дані»
  const snack = msg => { const s = $("snack"); s.textContent = msg; s.classList.add("show"); clearTimeout(snack.t); snack.t = setTimeout(() => s.classList.remove("show"), 7000); };
  $("refresh").href = CONFIG.updateUrl;
  $("refresh").addEventListener("click", () =>
    snack("Відкрито GitHub Actions: натисніть «Run workflow». Нові дані з'являться на сайті через 5–15 хв після завершення."));

  // ---------- блоки
  const dayAvg = (z, d, sel = () => true) => mean(HOURS.filter(sel).map(h => price(z, d, h)).filter(v => v != null));

  function renderTiles(dates) {
    $("tiles").innerHTML = ZONES.filter(z => state.zones.has(z.id)).map(z => {
      const d = [...dates].reverse().find(x => D.rdn[z.id][x]); // сусіди публікують D+1 пізніше
      if (!d) return "";
      const dPrev = addDays(d, -1), wk = datesIn(addDays(d, -7), dPrev);
      const v = dayAvg(z.id, d), p = dayAvg(z.id, dPrev), w = mean(wk.map(x => dayAvg(z.id, x)).filter(x => x != null));
      return `<div class="tile"><div class="k">${swatch(z)}${z.name} · base ${dm(d)}</div>
        <div class="v">${fmt(v)}</div><div class="d">до вчора ${pill(pct(v, p))} до 7 дн ${pill(pct(v, w))}</div></div>`;
    }).join("");
  }

  function zoneStats(z, dates) {
    const sel = HOURSEL[state.hours], all = [], daily = [], ranges = [], base = [], peak = [];
    for (const d of dates) {
      const day = [];
      for (const h of HOURS) {
        const v = price(z, d, h); if (v == null) continue;
        base.push(v); if (PEAK(h)) peak.push(v); if (sel(h)) { all.push(v); day.push(v); }
      }
      if (day.length) { daily.push(mean(day)); ranges.push(Math.max(...day) - Math.min(...day)); }
    }
    return { avg: mean(all), min: all.length ? Math.min(...all) : null, max: all.length ? Math.max(...all) : null,
      base: mean(base), peak: mean(peak), vol: std(daily), range: mean(ranges) };
  }
  function renderStats(dates) {
    const prev = datesIn(addDays(state.from, -dates.length), addDays(state.from, -1));
    const rows = ZONES.filter(z => state.zones.has(z.id)).map(z => {
      const s = zoneStats(z.id, dates), p = zoneStats(z.id, prev);
      return `<tr><td>${z.name}</td><td>${fmt(s.avg)}</td><td>${pill(pct(s.avg, p.avg))}</td><td>${fmt(s.base)}</td><td>${fmt(s.peak)}</td>
        <td>${fmt(s.min)}</td><td>${fmt(s.max)}</td><td>${fmt(s.vol)}</td><td>${fmt(s.range)}</td></tr>`;
    }).join("");
    $("tStats").innerHTML = `<thead><tr><th>Країна</th><th>Середня</th><th>Δ до попер.</th><th>Base</th><th>Peak</th>
      <th>Мін</th><th>Макс</th><th>Волатильність</th><th>Розмах доби</th></tr></thead><tbody>${rows}</tbody>`;
  }

  function renderDay() {
    const d = state.day; $("day").value = d;
    const zs = ZONES.filter(z => state.zones.has(z.id)), ns = zs.filter(z => z.id !== "UA"), hasUA = state.zones.has("UA");
    drawChart("cDay", HOUR_LABELS, zs.map(z => ({ label: z.name, c: z.c, data: HOURS.map(h => price(z.id, d, h)) })),
      { allTicks: true, xTitle: "Година (CET)", titlePrefix: "Година" });
    const head = `<tr><th>Година</th>${zs.map(z => `<th>${z.name}</th>`).join("")}` +
      (hasUA ? ns.map(z => `<th>${z.id} − UA</th>`).join("") : "") + "</tr>";
    const body = HOURS.map(h => {
      const ua = price("UA", d, h);
      const spr = hasUA ? ns.map(z => { const x = price(z.id, d, h); return colored(x == null || ua == null ? null : x - ua); }).join("") : "";
      return `<tr class="${PEAK(h) ? "peak" : ""}"><td>${h + 1}</td>${zs.map(z => `<td>${fmt(price(z.id, d, h), 2)}</td>`).join("")}${spr}</tr>`;
    }).join("");
    const total = (label, sel) => `<tr class="total"><td>${label}</td>${zs.map(z => `<td>${fmt(dayAvg(z.id, d, sel), 2)}</td>`).join("")}` +
      (hasUA ? ns.map(() => "<td></td>").join("") : "") + "</tr>";
    $("tDay").innerHTML = `<thead>${head}</thead><tbody>${body}${total("Base", () => true)}${total("Peak 9–20", PEAK)}</tbody>`;
  }

  /** Маржа торгівлі «купую в a, продаю в b» за годину; m = null, якщо на перетині немає потужності. */
  function margin(a, b, d, h, opts = {}) {
    const pa = price(a, d, h), pb = price(b, d, h), k = crossKey(a, b);
    if (pa == null || pb == null) return { buy: pa, sell: pb, spread: null, c: null, m: null };
    const c = opts.manualCross != null ? opts.manualCross : k ? cross(k, d, h) : 0;
    const m = c == null ? null : pb - pa - c - (opts.cost || 0);
    return { buy: pa, sell: pb, spread: pb - pa, c, m, noCrossData: !k && opts.manualCross == null };
  }

  function renderArb(dates) {
    const A = $("arbA").value, B = $("arbB").value, za = ZONE[A], zb = ZONE[B], d = state.arbDay;
    $("arbDay").value = d;
    $("arbSum").innerHTML = A === B ? "" : [[A, B], [B, A]].map(([x, y]) => {
      const plus = []; let hrs = 0;
      for (const dd of dates) for (const h of HOURS) { const r = margin(x, y, dd, h); if (r.m == null) continue; hrs++; if (r.m > 0) plus.push(r.m); }
      return `<div class="tile"><div class="k">${swatch(ZONE[x])}${ZONE[x].name} → ${ZONE[y].name} · за період</div>
        <div class="v">${plus.length} год у плюс</div><div class="d">${hrs ? fmt(plus.length / hrs * 100, 0) + "% годин" : "немає даних"} · сер. маржа ${fmt(mean(plus))}</div></div>`;
    }).join("");
    drawChart("cArb", HOUR_LABELS, [
      { label: za.name, c: za.c, data: HOURS.map(h => price(A, d, h)) },
      { label: zb.name, c: zb.c, data: HOURS.map(h => price(B, d, h)) }], { allTicks: true, xTitle: "Година (CET)", titlePrefix: "Година" });
    const hasCross = crossKey(A, B) || crossKey(B, A);
    const head = `<tr><th>Година</th><th>${za.name}</th><th>${zb.name}</th><th>Спред ${B} − ${A}</th>` +
      (hasCross ? `<th>Перетин ${A}→${B}</th><th>Маржа ${A}→${B}</th><th>Перетин ${B}→${A}</th><th>Маржа ${B}→${A}</th>` : "") + "</tr>";
    const cell = r => r.c == null ? `<td>—</td><td class="note">немає потужності</td>` : `<td>${fmt(r.c, 2)}</td>${colored(r.m)}`;
    $("tArb").innerHTML = `<thead>${head}</thead><tbody>${HOURS.map(h => {
      const ab = margin(A, B, d, h), ba = margin(B, A, d, h);
      return `<tr class="${PEAK(h) ? "peak" : ""}"><td>${h + 1}</td><td>${fmt(ab.buy, 2)}</td><td>${fmt(ab.sell, 2)}</td>${colored(ab.spread)}` +
        (hasCross ? cell(ab) + cell(ba) : "") + "</tr>";
    }).join("")}</tbody>`;
  }

  // ---------- головний рендер
  const listeners = [];
  function render() {
    if (state.from > state.to) [state.from, state.to] = [state.to, state.from];
    const dates = datesIn(state.from, state.to);
    if (state.agg === "hour" && dates.length > 31) state.agg = "day";
    store.set("hub-view", { agg: state.agg === "hour" ? "day" : state.agg, hours: state.hours, cur: state.cur });
    fromEl.value = state.from; toEl.value = state.to;
    syncers.forEach(f => f());
    document.querySelectorAll("#zones .chip").forEach(b => b.setAttribute("aria-pressed", String(state.zones.has(b.dataset.z))));
    renderDay();
    if (!dates.length) { listeners.forEach(f => f()); return; }

    const zs = ZONES.filter(z => state.zones.has(z.id)), ns = zs.filter(z => z.id !== "UA");
    const single = dates.length === 1 && state.agg === "hour";
    const hourOpts = single ? { allTicks: true, xTitle: "Година (CET)", titlePrefix: "Година" } : {};
    const rdn = zs.map(z => ({ z, s: series((d, h) => price(z.id, d, h), dates) }));
    const labels = rdn.length ? rdn[0].s.labels : series(() => null, dates).labels;
    drawChart("cRdn", labels, rdn.map(({ z, s }) => ({ label: z.name, c: z.c, data: s.values })), hourOpts);
    const aggName = { hour: "годину", day: "добу", month: "місяць", year: "рік" }[state.agg];
    $("rdnSub").textContent = `${dates.length === 1 ? dm(dates[0]) : `${dm(dates[0])}–${dm(dates[dates.length - 1])}`} · ${unit()} · середнє за ${aggName}`;

    drawChart("cSpread", labels, ns.map(z => ({ label: z.name, c: z.c,
      data: series((d, h) => { const a = price(z.id, d, h), b = price("UA", d, h); return a == null || b == null ? null : a - b; }, dates).values })), hourOpts);
    const sel = HOURSEL[state.hours];
    drawChart("cProfile", HOUR_LABELS, zs.map(z => ({ label: z.name, c: z.c,
      data: HOURS.map(h => sel(h) ? mean(dates.map(d => price(z.id, d, h)).filter(v => v != null)) : null) })),
      { allTicks: true, xTitle: "Година (CET)", titlePrefix: "Година" });
    drawChart("cExp", labels, ns.map(z => ({ label: `UA → ${z.id}`, c: z.c, data: series((d, h) => cross(`UA-${z.id}`, d, h), dates).values })), hourOpts);
    drawChart("cImp", labels, ns.map(z => ({ label: `${z.id} → UA`, c: z.c, data: series((d, h) => cross(`${z.id}-UA`, d, h), dates).values })), hourOpts);

    renderTiles(dates); renderStats(dates); renderArb(dates);
    listeners.forEach(f => f());
  }

  $("freshText").textContent = `Дані до ${dm(lastDate)} · оновлено ${D.updated.slice(8, 10)}.${D.updated.slice(5, 7)} ${D.updated.slice(11)}`;
  syncThemeIcon();

  // спільне API для калькулятора (calc.js)
  window.Hub = { D, ZONES, ZONE, HOURS, HOUR_LABELS, PEAK, HOURSEL, state, firstDate, lastDate, addDays, datesIn, fmt, mean,
    price, cross, crossKey, margin, unit, money, drawChart, segmented, colored, onRender: f => listeners.push(f), render };
  document.addEventListener("DOMContentLoaded", render);
})();
