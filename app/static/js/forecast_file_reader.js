/* Reads a (possibly many-GB) file in the browser in chunks, line by line into a ForecastTable, reporting progress.
   Nothing is uploaded: only the latest values per column are kept and later sent with the forecast. */
class ForecastFileReader {
  static KINDS = [
    [[0x50, 0x4b, 0x03, 0x04], "an Excel (.xlsx) or other zipped file. Save it as CSV in Excel (File > Save As > CSV) and open that"],
    [[0xd0, 0xcf, 0x11, 0xe0], "an old Excel (.xls) file. Save it as CSV in Excel (File > Save As > CSV) and open that"],
    [[0x25, 0x50, 0x44, 0x46], "a PDF. Copy the table out of it, or export it as CSV"],
    [[0x89, 0x50, 0x4e, 0x47], "a picture (PNG), not a table of numbers"],
    [[0xff, 0xd8, 0xff], "a picture (JPEG), not a table of numbers"],
    [[0x47, 0x49, 0x46, 0x38], "a picture (GIF), not a table of numbers"],
    [[0x1f, 0x8b], "a compressed (.gz) file. Unpack it first"],
  ];

  /* The text encoding to read `file` with; throws a plain-words error for a file that isn't text. */
  static async encodingOf(file) {
    if (!file.size) throw new Error(`${file.name} is empty`);
    const head = new Uint8Array(await file.slice(0, 65536).arrayBuffer());
    const starts = (bytes) => bytes.every((b, i) => head[i] === b);
    for (const [magic, what] of ForecastFileReader.KINDS) if (starts(magic)) throw new Error(`${file.name} looks like ${what}.`);
    if (starts([0xff, 0xfe])) return "utf-16le";
    if (starts([0xfe, 0xff])) return "utf-16be";
    const zeros = head.reduce((n, b) => n + (b === 0), 0);
    if (zeros > head.length / 100) throw new Error(`${file.name} doesn't look like text. Open a CSV or a plain list of numbers.`);
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(head.subarray(0, ForecastFileReader.lastCompleteChar(head)));
      return "utf-8";
    } catch (_) {
      return "windows-1252"; // older Excel CSV exports
    }
  }

  /* Cuts a UTF-8 sample before a character the 64 KB slice split in half. */
  static lastCompleteChar(bytes) {
    let end = bytes.length;
    for (let i = 1; i <= 3 && end - i >= 0; i++) {
      const b = bytes[end - i];
      if ((b & 0xc0) === 0xc0) return end - i; // a lead byte whose tail may be cut off
      if ((b & 0x80) === 0) break;
    }
    return end;
  }

  /* Resolves to ForecastTable.finish()'s result; rejects with an AbortError when `signal` aborts. */
  static async read(file, maxValues, onProgress, signal) {
    const encoding = await ForecastFileReader.encodingOf(file);
    const table = new ForecastTable(maxValues);
    const reader = file.stream().getReader();
    const decoder = new TextDecoder(encoding);
    let carry = "";
    let done = 0;
    let lastReport = 0;
    try {
      for (;;) {
        if (signal.aborted) {
          await reader.cancel();
          throw new DOMException("Reading cancelled", "AbortError");
        }
        const { value, done: finished } = await reader.read();
        if (finished) break;
        done += value.byteLength;
        const text = carry + decoder.decode(value, { stream: true });
        const lines = text.split(/\r\n|\r|\n/);
        carry = lines.pop();
        for (const line of lines) table.addLine(line);
        const now = performance.now();
        if (now - lastReport > 100) {
          lastReport = now;
          onProgress(done, file.size);
          await new Promise((r) => setTimeout(r)); // let the page repaint between chunks
        }
      }
    } finally {
      reader.releaseLock();
    }
    table.addLine(carry + decoder.decode());
    onProgress(file.size, file.size);
    const result = table.finish();
    if (encoding === "windows-1252") result.notes.push("Read as Windows-1252 text (an older Excel export)");
    return result;
  }

  /* A small file's text, decoded the same way, for the text box. */
  static async text(file) {
    return new TextDecoder(await ForecastFileReader.encodingOf(file)).decode(await file.arrayBuffer());
  }
}
