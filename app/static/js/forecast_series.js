/* Forecast page: the latest values of a column (TailBuffer), and turning a column with gaps and dates into a clean,
   oldest-first series with notes on what was fixed (ForecastSeries.prepare). */
class TailBuffer {
  constructor(max) {
    this.max = max;
    this.items = [];
    this.total = 0;
  }

  push(value) {
    this.items.push(value);
    this.total++;
    if (this.items.length >= 2 * this.max) this.items = this.items.slice(-this.max); // trim in batches
  }

  values() {
    return this.items.slice(-this.max);
  }
}

class ForecastSeries {
  static MIN_VALUES = 2;
  static FEW_VALUES = 32;

  /* { values, dates, step, notes: [{ text, warn }] }: values ready to send, dates (or null) aligned to them. */
  static prepare(column, allDates) {
    const notes = [];
    let values = column.values.slice();
    let dates = allDates && allDates.length === values.length ? allDates.slice() : null;
    if (dates && dates.filter((d) => d !== null).length < values.length / 2) dates = null;

    // Newest first (a common export order): turn it around, the model reads oldest first.
    const known = dates ? dates.filter((d) => d !== null) : [];
    if (known.length > 2 && known[0] > known[known.length - 1]) {
      values.reverse();
      dates.reverse();
      notes.push({ text: "Rows were newest first; read oldest first" });
    }

    // Gaps at the ends are dropped; gaps inside are filled in a straight line between their neighbours.
    const first = values.findIndex((v) => v !== null);
    const last = values.length - 1 - [...values].reverse().findIndex((v) => v !== null);
    if (first === -1) return { values: [], dates: null, step: null, notes: [{ text: "This column has no numbers", warn: true }] };
    values = values.slice(first, last + 1);
    if (dates) dates = dates.slice(first, last + 1);
    const filled = ForecastSeries.fillGaps(values);
    if (filled) notes.push({ text: `${filled.toLocaleString()} empty or unreadable cell${filled === 1 ? "" : "s"} filled from the values around ${filled === 1 ? "it" : "them"}`, warn: filled > values.length / 10 });

    const step = dates ? ForecastSeries.checkDates(dates, notes) : null;
    if (values.length < ForecastSeries.MIN_VALUES) notes.push({ text: "At least 2 values are needed", warn: true });
    else if (values.length < ForecastSeries.FEW_VALUES) notes.push({ text: `Only ${values.length} values: the forecast may be rough`, warn: true });
    if (values.length > 1 && values.every((v) => v === values[0])) notes.push({ text: "Every value is the same: the forecast will be flat", warn: true });
    return { values, dates: step ? dates : null, step, notes };
  }

  /* Fills null runs by straight-line interpolation; returns how many were filled. */
  static fillGaps(values) {
    let filled = 0;
    for (let i = 0; i < values.length; i++) {
      if (values[i] !== null) continue;
      let j = i;
      while (values[j] === null) j++;
      const a = values[i - 1];
      const b = values[j];
      for (let k = i; k < j; k++) values[k] = a + ((b - a) * (k - i + 1)) / (j - i + 1);
      filled += j - i;
      i = j;
    }
    return filled;
  }

  /* The time step, with notes on dates that are missing, repeated, out of order or unevenly spaced. */
  static checkDates(dates, notes) {
    for (let i = 0; i < dates.length; i++) if (dates[i] === null) dates[i] = i ? dates[i - 1] : null;
    if (dates[0] === null) return null;
    const step = ForecastDates.step(dates);
    if (!step || step <= 0) {
      notes.push({ text: "The dates are not in order, so the time step is unknown", warn: true });
      return null;
    }
    let repeated = 0;
    let backwards = 0;
    let uneven = 0;
    const loose = ForecastDates.unit(step).months ? 0.12 : 0.01; // months and years vary in length
    for (let i = 1; i < dates.length; i++) {
      const d = dates[i] - dates[i - 1];
      if (d === 0) repeated++;
      else if (d < 0) backwards++;
      else if (Math.abs(d - step) > step * loose) uneven++;
    }
    if (repeated) notes.push({ text: `${repeated.toLocaleString()} repeated date${repeated === 1 ? "" : "s"}`, warn: true });
    if (backwards) notes.push({ text: `${backwards.toLocaleString()} date${backwards === 1 ? " goes" : "s go"} back in time`, warn: true });
    if (uneven > dates.length / 20) notes.push({ text: `Uneven spacing: ${uneven.toLocaleString()} gaps differ from the usual ${ForecastDates.describe(step)}`, warn: true });
    return step;
  }
}
