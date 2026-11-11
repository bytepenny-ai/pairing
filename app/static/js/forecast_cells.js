/* Forecast page cells: split a CSV line (quotes respected) and read a number the way spreadsheets write it. */
class ForecastCells {
  static MISSING = new Set(["", "na", "n/a", "nan", "null", "none", "-", "--", "?", "#n/a", "missing"]);

  /* Cells of one line; a quoted cell may hold the separator ("1,234" in a comma file). */
  static split(line, sep) {
    if (!line.includes('"')) return line.split(sep).map((c) => c.trim());
    const cells = [];
    let cell = "";
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = !quoted;
      } else if (ch === sep && !quoted) {
        cells.push(cell.trim());
        cell = "";
      } else cell += ch;
    }
    cells.push(cell.trim());
    return cells;
  }

  static isMissing(cell) {
    return ForecastCells.MISSING.has(String(cell).trim().toLowerCase());
  }

  /* A finite number, else null. `decimalComma`: "1.234,5" is 1234.5 (most of Europe); otherwise "1,234.5" is. */
  static number(cell, decimalComma = false) {
    let text = String(cell).replace(/[\s '$€£¥₪%]/g, "");
    if (text.startsWith("(") && text.endsWith(")")) text = `-${text.slice(1, -1)}`; // accounting negatives
    if (decimalComma) {
      // Dots only as thousands groups ("1.234,5"); "01.02.2026" stays text (a date).
      if (/^[-+]?\d{1,3}(\.\d{3})+(,\d*)?$/.test(text)) text = text.replace(/\./g, "");
      text = text.replace(",", ".");
    }
    else if (/^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(text)) text = text.replace(/,/g, "");
    if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(text)) return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  }

  /* Whether the sample's numbers use a decimal comma: "12,5" style beats "12.5" style. */
  static decimalCommaIn(cells) {
    let comma = 0;
    let dot = 0;
    for (const raw of cells) {
      const c = String(raw).replace(/[\s ]/g, "");
      if (/^[-+]?\d{1,3}(\.\d{3})*,\d+$/.test(c) && !/^[-+]?\d{1,3},\d{3}$/.test(c)) comma++;
      else if (/^[-+]?\d+(,\d{3})*\.\d+$/.test(c)) dot++;
    }
    return comma > dot;
  }
}
