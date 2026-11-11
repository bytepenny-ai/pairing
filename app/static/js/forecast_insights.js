/* Forecast page "About this forecast" panel: what was forecast, from which data, and what the result says. */
class ForecastInsights {
  static FLAT_PERCENT = 2; // a change smaller than this reads as "about flat"
  static COMMON_PERIODS = [4, 7, 12, 24, 48, 52, 60, 96, 144, 168, 288, 336, 365, 672, 1440, 2016, 10080];

  constructor(root) {
    this.list = root.querySelector("[data-insights-list]");
    this.notes = root.querySelector("[data-insights-notes]");
  }

  /* `run`: { model, column, prepared, forecast, horizon, seconds }. */
  render(run) {
    const rows = ForecastInsights.rows(run);
    this.list.innerHTML = rows
      .map(([label, value, hint]) =>
        `<div class="py-1.5 border-t border-slate-800 first:border-0"><dt class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label)}</dt>` +
        `<dd class="text-sm text-slate-200"${hint ? ` title="${escapeHtml(hint)}"` : ""}>${escapeHtml(value)}</dd></div>`)
      .join("");
    const notes = run.prepared.notes.concat(run.tableNotes.map((text) => ({ text })));
    this.notes.innerHTML = notes
      .map((n) => `<li class="${n.warn ? "text-warning-400" : "text-slate-400"}">${escapeHtml(n.text)}</li>`)
      .join("");
    this.notes.parentElement.classList.toggle("hidden", !notes.length);
  }

  static rows({ model, column, prepared, forecast, horizon, seconds }) {
    const fmt = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
    const pct = (v) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
    const { values, dates, step } = prepared;
    const last = values[values.length - 1];
    const end = forecast.point[horizon - 1];
    const low = forecast.quantiles["0.1"][horizon - 1];
    const high = forecast.quantiles["0.9"][horizon - 1];
    const recent = values.slice(-horizon);
    const recentMean = ForecastInsights.mean(recent);
    const nextMean = ForecastInsights.mean(forecast.point);
    const change = recentMean ? (100 * (nextMean - recentMean)) / Math.abs(recentMean) : 0;
    const rows = [
      ["Model", model.replace(/^hf\.co\//, "")],
      ["Data", `${column.name} · ${values.length.toLocaleString()} values used${column.total > values.length ? ` of ${column.total.toLocaleString()}` : ""}`],
      ["Time step", step ? ForecastDates.describe(step) : "Not known (no dates found)"],
      ["Forecast length", `${horizon} step${horizon === 1 ? "" : "s"}${step ? ` (${ForecastInsights.span(step, horizon)})` : ""}`],
    ];
    if (step) {
      const future = ForecastDates.after(dates[dates.length - 1], step, horizon);
      rows.push(["Covers", `${ForecastDates.format(future[0], step)} to ${ForecastDates.format(future[horizon - 1], step)}`]);
    }
    rows.push(
      ["Last value", fmt(last)],
      ["End of forecast", `${fmt(end)} (${pct(last ? (100 * (end - last)) / Math.abs(last) : 0)} vs the last value)`],
      ["Direction", ForecastInsights.direction(change, horizon), "The forecast's average against the same number of latest values"],
      ["Likely range at the end", `${fmt(low)} to ${fmt(high)}`, "8 times out of 10 the real value should fall in this range"],
      ["Repeating pattern", ForecastInsights.pattern(values, step)],
      ["Time taken", `${seconds.toFixed(1)} s`],
    );
    return rows;
  }

  static direction(change, horizon) {
    const word = Math.abs(change) < ForecastInsights.FLAT_PERCENT ? "About flat" : change > 0 ? "Rising" : "Falling";
    return `${word} (${change > 0 ? "+" : ""}${change.toFixed(1)}% vs the last ${horizon} values)`;
  }

  static span(step, count) {
    const unit = ForecastDates.unit(step);
    if (unit.months) {
      const months = unit.months * count;
      return months % 12 === 0 ? `${months / 12} year${months === 12 ? "" : "s"}` : `${months} months`;
    }
    return ForecastDates.duration(step * count);
  }

  /* The strongest cycle in the values (autocorrelation), as "every 24 steps (1 day)", or "None found". */
  static pattern(values, step) {
    const period = ForecastInsights.period(values);
    if (!period) return "None found";
    return `Every ${period.toLocaleString()} steps${step ? ` (${ForecastInsights.span(step, period)})` : ""}`;
  }

  static period(values) {
    const n = values.length;
    if (n < 8) return null;
    // Remove the straight-line trend, so a rise isn't taken for a cycle.
    const xm = (n - 1) / 2;
    const ym = ForecastInsights.mean(values);
    let sxy = 0;
    let sxx = 0;
    for (let i = 0; i < n; i++) {
      sxy += (i - xm) * (values[i] - ym);
      sxx += (i - xm) ** 2;
    }
    const slope = sxy / sxx;
    const x = values.map((v, i) => v - ym - slope * (i - xm));
    const variance = x.reduce((s, v) => s + v * v, 0);
    if (!variance) return null;
    const maxLag = Math.min(Math.floor(n / 2), Math.floor(5e7 / n)); // bounded work, even for 16k values
    const acf = [1];
    for (let lag = 1; lag <= maxLag; lag++) {
      let s = 0;
      for (let i = lag; i < n; i++) s += x[i] * x[i - lag];
      acf.push(s / variance);
    }
    // The top of the first hump after the curve dips below zero, if it is strong enough to mean something.
    let lag = 1;
    while (lag < maxLag && acf[lag] > 0) lag++;
    while (lag < maxLag && acf[lag] <= 0) lag++;
    let best = null;
    for (; lag <= maxLag && acf[lag] > 0; lag++) if (best === null || acf[lag] > acf[best]) best = lag;
    if (best === null || acf[best] < 0.3) return null;
    // Noise moves the top a step or two: prefer a common cycle (a week of days, a day of minutes...) that close.
    const near = ForecastInsights.COMMON_PERIODS.find((c) => Math.abs(c - best) <= Math.max(1, c / 100) && acf[c] >= acf[best] - 0.05);
    return near ?? best;
  }

  static mean(values) {
    return values.length ? values.reduce((s, v) => s + v, 0) / values.length : 0;
  }
}
