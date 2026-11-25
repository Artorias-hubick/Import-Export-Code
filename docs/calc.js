/* Калькулятор прибутковості (ліва панель): купівля на РДН країни A, продаж на РДН країни B. */
(() => {
  "use strict";
  const H = window.Hub;
  if (!H) return;
  const $ = id => document.getElementById(id);
  // за замовчуванням — остання доба, на яку опубліковані ціни всіх країн
  const fullDay = [...H.datesIn(H.firstDate, H.lastDate)].reverse().find(d => H.ZONES.every(z => H.D.rdn[z.id][d])) || H.lastDate;
  const c = { scope: "day", hours: "all", crossMode: "auto", day: fullDay, from: 1, to: 24 };

  // ---------- поля
  [$("cBuy"), $("cSell")].forEach((sel, i) => {
    H.ZONES.forEach(z => sel.add(new Option(z.name, z.id)));
    sel.value = i ? "UA" : "HU";
    sel.addEventListener("change", update);
  });
  $("cSwap").addEventListener("click", () => { [$("cBuy").value, $("cSell").value] = [$("cSell").value, $("cBuy").value]; update(); });
  [$("cFrom"), $("cTo")].forEach((sel, i) => {
    H.HOUR_LABELS.forEach(l => sel.add(new Option(l, l)));
    sel.value = i ? "24" : "1";
    sel.addEventListener("change", () => { c.from = +$("cFrom").value; c.to = +$("cTo").value; update(); });
  });
  ["cMw", "cCost", "cCross"].forEach(id => $(id).addEventListener("input", update));
  $("cOnlyPlus").addEventListener("change", update);

  const dayEl = $("kDay");
  dayEl.min = H.firstDate; dayEl.max = H.lastDate;
  const shift = n => { const v = H.addDays(c.day, n); if (v >= H.firstDate && v <= H.lastDate) { c.day = v; update(); } };
  $("cPrev").addEventListener("click", () => shift(-1));
  $("cNext").addEventListener("click", () => shift(1));
  dayEl.addEventListener("change", () => { if (dayEl.value) { c.day = dayEl.value; update(); } });

  const syncers = [
    H.segmented("cScope", [["day", "Доба"], ["period", "Період з фільтра"]], v => v === c.scope, v => { c.scope = v; update(); }),
    H.segmented("cHours", [["all", "Усі"], ["peak", "Пік"], ["off", "Поза піком"], ["custom", "Свої"]], v => v === c.hours,
      v => { c.hours = v; update(); }),
    H.segmented("cCrossMode", [["auto", "З аукціону"], ["manual", "Вручну"]], v => v === c.crossMode, v => { c.crossMode = v; update(); }),
  ];

  const num = id => { const v = parseFloat($(id).value); return isFinite(v) && v >= 0 ? v : 0; };
  const hourSel = h => c.hours === "custom"
    ? (c.from <= c.to ? h + 1 >= c.from && h + 1 <= c.to : h + 1 >= c.from || h + 1 <= c.to)
    : H.HOURSEL[c.hours](h);

  // ---------- розрахунок
  function compute(A, B, dates) {
    const mw = num("cMw"), cost = num("cCost"), only = $("cOnlyPlus").checked;
    const manual = c.crossMode === "manual" ? num("cCross") : null;
    const perHour = H.HOURS.map(() => ({ buy: [], sell: [], cr: [], m: [], profit: 0, traded: 0 }));
    let noCrossData = false;
    for (const d of dates) for (const h of H.HOURS) {
      if (!hourSel(h)) continue;
      const r = H.margin(A, B, d, h, { cost, manualCross: manual });
      if (r.noCrossData) noCrossData = true;
      const ph = perHour[h];
      if (r.buy != null) ph.buy.push(r.buy);
      if (r.sell != null) ph.sell.push(r.sell);
      if (r.m == null) continue; // немає цін або потужності на перетині
      ph.cr.push(r.c); ph.m.push(r.m);
      if (!only || r.m > 0) { ph.profit += r.m * mw; ph.traded++; }
    }
    const total = perHour.reduce((s, p) => s + p.profit, 0);
    const traded = perHour.reduce((s, p) => s + p.traded, 0);
    const tradable = perHour.reduce((s, p) => s + p.m.length, 0);
    const plusHours = perHour.reduce((s, p) => s + p.m.filter(x => x > 0).length, 0);
    return { perHour, total, traded, tradable, plusHours, mw, noCrossData };
  }

  // ---------- вивід
  function update() {
    const A = $("cBuy").value, B = $("cSell").value;
    syncers.forEach(f => f());
    $("cCustom").hidden = c.hours !== "custom";
    $("cCross").hidden = c.crossMode !== "manual";
    $("cDayRow").hidden = c.scope !== "day";
    dayEl.value = c.day;
    $("cCostLbl").textContent = `Інші витрати, ${H.money()}/МВт·год`;
    $("cCross").placeholder = `Ціна перетину, ${H.unit()}`;

    const dates = c.scope === "day" ? [c.day] : H.datesIn(H.state.from, H.state.to);
    const res = A === B ? null : compute(A, B, dates);
    const box = $("cResult");
    if (!res) {
      box.className = "result"; box.innerHTML = "Оберіть дві різні країни";
      $("cTable").innerHTML = ""; $("cHint").textContent = ""; H.drawChart("cChart", H.HOUR_LABELS, []); return;
    }
    const period = c.scope === "day" ? `за ${c.day.slice(8)}.${c.day.slice(5, 7)}` : `за ${dates.length} дн.`;
    const avgM = res.traded ? res.total / (res.traded * res.mw || 1) : null;
    box.className = "result" + (res.total < 0 ? " loss" : "");
    box.innerHTML = `<div class="sub" style="color:inherit;opacity:.85">${H.ZONE[A].name} → ${H.ZONE[B].name} · ${period}</div>
      <div class="big">${res.total > 0 ? "+" : ""}${H.fmt(res.total, 0)} ${H.money()}</div>
      <div class="meta"><span>Прибуткових годин: <b>${res.plusHours}</b> з ${res.tradable} доступних</span>
        <span>Торгуємо: ${res.traded} год × ${H.fmt(res.mw, 0)} МВт = ${H.fmt(res.traded * res.mw, 0)} МВт·год</span>
        <span>Середня маржа: ${H.fmt(avgM, 2)} ${H.unit()}</span></div>`;

    const avg = a => H.mean(a);
    const marg = res.perHour.map(p => avg(p.m));
    H.drawChart("cChart", H.HOUR_LABELS, [{
      label: c.scope === "day" ? "Маржа" : "Середня маржа", data: marg,
      colors: marg.map(v => v == null ? "transparent" : getComputedStyle(document.documentElement).getPropertyValue(v > 0 ? "--up" : "--down").trim()),
    }], { type: "bar", horizontal: true, allTicks: true, xTitle: "Година (CET)", titlePrefix: "Година", legend: false });

    const rows = H.HOURS.filter(hourSel).map(h => {
      const p = res.perHour[h];
      const m = avg(p.m);
      return `<tr class="${H.PEAK(h) ? "peak" : ""}"><td>${h + 1}</td><td>${H.fmt(avg(p.buy), 2)}</td><td>${H.fmt(avg(p.sell), 2)}</td>
        <td>${p.cr.length ? H.fmt(avg(p.cr), 2) : '<span class="note">нема</span>'}</td>${H.colored(m)}<td>${p.profit ? H.fmt(p.profit, 0) : "—"}</td></tr>`;
    }).join("");
    $("cTable").innerHTML = `<thead><tr><th>Год</th><th>Купівля</th><th>Продаж</th><th>Перетин</th><th>Маржа</th><th>Прибуток</th></tr></thead><tbody>${rows}</tbody>`;
    $("cHint").textContent = (res.noCrossData
      ? "Для цієї пари немає даних аукціону перетину (є лише кордони з Україною): ціна перетину взята 0, вкажіть її вручну. "
      : "Години без потужності на перетині не торгуються. ") + `Ціни в ${H.unit()}, години CET.`;
  }

  H.onRender(update);
})();
