/* Forecast page dates: parse a label cell to UTC milliseconds, find the time step, and name future steps.
   UTC throughout, so daylight-saving changes never bend the steps. */
class ForecastDates {
  static ISO = /^(\d{4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;
  static DMY = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/;
  static DAY = 86_400_000;

  /* UTC ms, or null. `dayFirst` reads 05/01/2026 as 5 January (decided per file by ForecastTable). */
  static parse(cell, dayFirst = false) {
    const text = String(cell).trim().replace(/^"|"$/g, "");
    let m = ForecastDates.ISO.exec(text);
    if (m) return ForecastDates.utc(+m[1], +m[2], m[3] ? +m[3] : 1, m[4], m[5], m[6]);
    m = ForecastDates.DMY.exec(text);
    if (m) {
      const [a, b] = [+m[1], +m[2]];
      const [day, month] = dayFirst ? [a, b] : [b, a];
      return ForecastDates.utc(+m[3], month, day, m[4], m[5], m[6]);
    }
    if (/^\d{10}(\d{3})?$/.test(text)) return text.length === 10 ? +text * 1000 : +text; // Unix time
    if (/^\d{4}$/.test(text) && +text > 1800 && +text < 2200) return Date.UTC(+text, 0, 1); // a year
    return null;
  }

  /* Whether day/month/year dates in `cells` put the day first: a part above 12 proves it, dots ("05.01.2026")
     usually mean it, and otherwise the reading with the more even steps wins. */
  static dayFirst(cells) {
    const dates = cells.map((c) => ForecastDates.DMY.exec(String(c).trim())).filter(Boolean);
    if (!dates.length) return false;
    if (dates.some((m) => +m[1] > 12)) return true;
    if (dates.some((m) => +m[2] > 12)) return false;
    if (dates.some((m) => m[0].includes("."))) return true;
    const evenness = (first) => {
      const ms = dates.map((m) => ForecastDates.utc(+m[3], first ? +m[2] : +m[1], first ? +m[1] : +m[2]));
      const step = ForecastDates.step(ms);
      return ms.filter((d, i) => i && d - ms[i - 1] === step).length;
    };
    return evenness(true) > evenness(false);
  }

  static utc(y, mo, d, h, mi, s) {
    if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
    return Date.UTC(y, mo - 1, d, +(h || 0), +(mi || 0), +(s || 0));
  }

  /* The usual gap between dates, in ms (the median, so a few gaps don't change it). */
  static step(dates) {
    const diffs = [];
    for (let i = 1; i < dates.length; i++) diffs.push(dates[i] - dates[i - 1]);
    if (!diffs.length) return null;
    diffs.sort((a, b) => a - b);
    return diffs[Math.floor(diffs.length / 2)] || null;
  }

  /* Calendar months and years stay whole ("2026-01" then "2026-02"), whatever their length in days. */
  static unit(step) {
    const days = step / ForecastDates.DAY;
    if (days >= 360 && days <= 370) return { months: 12 };
    if (days >= 89 && days <= 93) return { months: 3 };
    if (days >= 28 && days <= 31) return { months: 1 };
    return { ms: step };
  }

  static after(last, step, count) {
    const unit = ForecastDates.unit(step);
    const out = [];
    for (let i = 1; i <= count; i++) {
      if (unit.ms) out.push(last + unit.ms * i);
      else {
        const d = new Date(last);
        const month = d.getUTCMonth() + unit.months * i;
        const days = new Date(Date.UTC(d.getUTCFullYear(), month + 1, 0)).getUTCDate(); // 31 Jan + 1 month = 28/29 Feb
        out.push(Date.UTC(d.getUTCFullYear(), month, Math.min(d.getUTCDate(), days), d.getUTCHours(), d.getUTCMinutes()));
      }
    }
    return out;
  }

  /* A label as short as the step allows: a year, a month, a day, or a day with the time. */
  static format(ms, step) {
    const iso = new Date(ms).toISOString();
    const days = step / ForecastDates.DAY;
    if (days >= 360) return iso.slice(0, 4);
    if (days >= 28) return iso.slice(0, 7);
    if (days >= 1) return iso.slice(0, 10);
    return `${iso.slice(0, 10)} ${iso.slice(11, step % 60_000 ? 19 : 16)}`;
  }

  /* "1 hour", "15 minutes", "1 day"... for a step in ms. */
  static describe(step) {
    const unit = ForecastDates.unit(step);
    if (unit.months === 12) return "1 year";
    if (unit.months === 3) return "1 quarter";
    if (unit.months === 1) return "1 month";
    return ForecastDates.duration(step);
  }

  static duration(ms) {
    const units = [["week", 7 * ForecastDates.DAY], ["day", ForecastDates.DAY], ["hour", 3_600_000], ["minute", 60_000], ["second", 1000]];
    for (const [name, size] of units) {
      if (ms >= size && ms % size === 0) {
        const n = ms / size;
        return `${n.toLocaleString()} ${name}${n === 1 ? "" : "s"}`;
      }
    }
    return `${(ms / 1000).toLocaleString()} seconds`;
  }
}
