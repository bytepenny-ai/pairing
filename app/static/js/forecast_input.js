/* Forecast page input: lines of pasted numbers or a CSV table -> numeric columns (gaps kept as null) and the date
   column, if any. Fed line by line, so a huge file streams through it keeping only the latest values. No DOM. */
class ForecastTable {
  static SEPARATORS = [",", ";", "\t", "|"];
  static SNIFF_LINES = 50; // lines read before deciding the layout
  static DATE_NAME = /date|time|day|month|year|week|period|timestamp|datum|fecha|jahr|monat|^ds$/i;

  constructor(maxValues = 16384) {
    this.maxValues = maxValues;
    this.pending = [];
    this.layout = null;
    this.skipped = 0;
    this.notes = [];
  }

  addLine(raw) {
    const line = raw.trim();
    if (!line) return;
    if (this.layout) return this.addRow(line);
    this.pending.push(line);
    if (this.pending.length >= ForecastTable.SNIFF_LINES) this.sniff();
  }

  /* { columns: [{ name, values, total }], dates, skipped, notes } once every line is in. */
  finish() {
    if (!this.layout) this.sniff();
    const columns = this.layout.columns
      .filter((c) => c.buffer.total)
      .map((c) => ({ name: c.name, values: c.buffer.values(), total: c.buffer.total }));
    // Dates are kept as text and parsed here, only for the rows kept (fast on huge files).
    const dates = this.layout.dates ? this.layout.dates.buffer.values().map((c) => ForecastDates.parse(c, this.layout.dayFirst)) : null;
    return { columns, dates, dateName: this.layout.dates?.name ?? null, skipped: this.skipped, notes: this.notes };
  }

  sniff() {
    const lines = this.pending;
    this.pending = [];
    const sep = ForecastTable.separatorOf(lines);
    this.layout = sep ? this.tableLayout(lines, sep) : ForecastTable.listLayout(this.maxValues);
    for (const line of this.layout.dataLines ?? lines) this.addRow(line);
    delete this.layout.dataLines;
  }

  static listLayout(max) {
    return { sep: null, decimalComma: false, columns: [{ index: 0, name: "Values", buffer: new TailBuffer(max) }] };
  }

  tableLayout(lines, sep) {
    const rows = lines.map((l) => ForecastCells.split(l, sep));
    const width = ForecastTable.mostCommon(rows.map((r) => r.length));
    // Report titles or notes above the table have another width: skip them.
    const first = rows.findIndex((r) => r.length === width);
    if (first > 0) this.notes.push(`${first} line${first === 1 ? "" : "s"} above the table skipped`);
    const body = rows.slice(first);
    const decimalComma = sep !== "," && ForecastCells.decimalCommaIn(body.flat());
    if (decimalComma) this.notes.push("Decimal commas read (12,5 = 12.5)");
    const dayFirst = ForecastDates.dayFirst(body.flat());
    const isHeader = body[0].some((c) => !ForecastCells.isMissing(c) && ForecastCells.number(c, decimalComma) === null && ForecastDates.parse(c, dayFirst) === null);
    const header = isHeader ? body[0] : null;
    const data = isHeader ? body.slice(1) : body;
    const layout = { sep, decimalComma, dayFirst, columns: [], dates: null, dataLines: lines.slice(first + (isHeader ? 1 : 0)) };
    for (let index = 0; index < width; index++) {
      const name = (header && header[index]) || `Column ${index + 1}`;
      const cells = data.map((r) => r[index] ?? "").filter((c) => !ForecastCells.isMissing(c));
      const numbers = cells.filter((c) => ForecastCells.number(c, decimalComma) !== null).length;
      const dates = cells.map((c) => ForecastDates.parse(c, dayFirst)).filter((d) => d !== null);
      const datey = dates.length >= 0.8 * cells.length && cells.length > 0;
      // A date column, even when written as numbers (a year, Unix time), is the timeline, not data.
      if (!layout.dates && datey && (numbers < cells.length || ForecastTable.DATE_NAME.test(name) || ForecastTable.increasingEpochs(cells))) {
        layout.dates = { index, name, buffer: new TailBuffer(this.maxValues) };
      } else if (cells.length && numbers >= cells.length / 2) {
        layout.columns.push({ index, name, buffer: new TailBuffer(this.maxValues) });
      }
    }
    return layout;
  }

  addRow(line) {
    const { sep, decimalComma, columns, dates } = this.layout;
    if (!sep) {
      for (const token of line.split(/[\s,;]+/).filter(Boolean)) this.take(columns[0], token, false);
      return;
    }
    const cells = ForecastCells.split(line, sep);
    if (dates) dates.buffer.push(cells[dates.index] ?? "");
    for (const column of columns) this.take(column, cells[column.index] ?? "", decimalComma);
  }

  /* A number, or a gap (null) for a missing or unreadable cell, so the timeline never shifts. */
  take(column, cell, decimalComma) {
    const value = ForecastCells.number(cell, decimalComma);
    if (value === null && !ForecastCells.isMissing(cell)) this.skipped++;
    if (value === null && !this.layout.sep && !ForecastCells.isMissing(cell)) return; // a word in a plain list
    column.buffer.push(value);
  }

  static increasingEpochs(cells) {
    const values = cells.map(Number);
    return values.every((v, i) => /^\d{10}(\d{3})?$/.test(cells[i]) && (i === 0 || v > values[i - 1]));
  }

  static mostCommon(values) {
    const counts = new Map();
    for (const v of values) counts.set(v, (counts.get(v) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0][0];
  }

  /* The separator found on most lines (a table), or null for a plain list. */
  static separatorOf(lines) {
    let best = null;
    let bestCount = 0;
    for (const sep of ForecastTable.SEPARATORS) {
      const count = lines.filter((l) => l.includes(sep)).length;
      if (count > bestCount) [best, bestCount] = [sep, count];
    }
    if (best && lines.length === 1) return null; // "1,2,3" on one line is a list
    return bestCount >= Math.ceil(lines.length / 2) ? best : null;
  }
}

class ForecastInput {
  /* Parses pasted text through the same line-by-line path a streamed file takes. */
  static parse(text, maxValues = 16384) {
    const table = new ForecastTable(maxValues);
    for (const line of text.split(/\r?\n/)) table.addLine(line);
    return table.finish();
  }

  /* A sample series: four years of monthly sales with a trend and a yearly season. */
  static example() {
    const lines = ["month,sales"];
    for (let i = 0; i < 48; i++) {
      const year = 2023 + Math.floor(i / 12);
      const month = String((i % 12) + 1).padStart(2, "0");
      const sales = 200 + 3 * i + 40 * Math.sin((2 * Math.PI * i) / 12) + ((i * 37) % 11) - 5;
      lines.push(`${year}-${month},${sales.toFixed(1)}`);
    }
    return lines.join("\n");
  }
}
