/* The Forecast page (/forecast): paste numbers or read a file (any size, in the browser), pick a column, forecast it
   (POST /api/forecast, streamed NDJSON: heartbeats, then the result). */
class ForecastPage {
  static INLINE_FILE_BYTES = 512 * 1024; // smaller files open in the text box for editing

  constructor() {
    this.el = (id) => document.getElementById(id);
    this.input = this.el("forecast-input");
    this.columnSelect = this.el("forecast-column");
    this.modelSelect = this.el("forecast-model");
    this.horizonInput = this.el("forecast-horizon");
    this.runButton = this.el("forecast-run");
    this.status = this.el("forecast-status");
    this.progress = new ForecastProgress(this.el("forecast-progress"));
    this.chart = new ForecastChart(this.el("forecast-chart"));
    this.view = new ForecastResultView(this.el("forecast-table-body"));
    this.insights = new ForecastInsights(this.el("forecast-insights"));
    this.info = { max_series_length: 16384, limits: { max_file_mb: 1024 } };
    this.parsed = { columns: [], dates: null, skipped: 0, notes: [] };
    this.prepared = null;
    this.result = null;
    this.busy = false;
    this.bind();
    this.loadModels();
  }

  bind() {
    this.input.addEventListener("input", () => this.reparse());
    this.columnSelect.addEventListener("change", () => this.showColumn());
    this.modelSelect.addEventListener("change", () => this.updateRunButton());
    this.el("forecast-example").addEventListener("click", () => this.useText(ForecastInput.example()));
    this.el("forecast-file").addEventListener("change", (e) => this.readFile(e.target.files[0]));
    this.el("forecast-file-clear").addEventListener("click", () => this.useText(""));
    this.runButton.addEventListener("click", () => this.run());
    this.el("forecast-download").addEventListener("click", () => this.view.download(this.result));
    window.addEventListener("resize", () => this.result && this.draw());
  }

  async loadModels() {
    try {
      this.info = await api("/api/forecast/models");
      this.horizonInput.max = this.info.max_horizon;
      this.el("forecast-file-limit").textContent = `up to ${this.info.limits.max_file_mb} MB`;
      this.modelSelect.replaceChildren(...this.info.models.map((m) => new Option(m, m)));
      if (this.info.default_model) this.modelSelect.value = this.info.default_model; // Admin settings > Default models
      if (!this.info.engine_supports) this.setStatus("Forecasting needs the Matricxon engine; ask your admin.", true);
      else if (!this.info.models.length) this.setStatus("No forecasting model is installed yet; ask your admin.", true);
      this.updateRunButton();
    } catch (err) {
      this.setStatus(`Could not load forecasting models: ${err.message}`, true);
    }
  }

  useText(text) {
    this.el("forecast-file-chip").classList.add("hidden");
    this.input.classList.remove("hidden");
    this.el("forecast-file").value = "";
    this.input.value = text;
    this.reparse();
  }

  async readFile(file) {
    if (!file || this.busy) return;
    this.setStatus("");
    const maxBytes = this.info.limits.max_file_mb * 1024 * 1024;
    try {
      if (file.size > maxBytes) {
        throw new Error(`${file.name} is ${ForecastProgress.size(file.size)}; the limit is ${this.info.limits.max_file_mb} MB.`);
      }
      if (file.size <= ForecastPage.INLINE_FILE_BYTES) return this.useText(await ForecastFileReader.text(file));
    } catch (err) {
      this.el("forecast-file").value = "";
      return this.setStatus(err.message, true);
    }
    this.busy = true;
    const signal = this.progress.start(`Reading ${file.name}`);
    try {
      const parsed = await ForecastFileReader.read(file, this.info.max_series_length, (d, t) => this.progress.bytes(d, t), signal);
      this.input.classList.add("hidden");
      this.el("forecast-file-chip").classList.remove("hidden");
      this.el("forecast-file-name").textContent = `${file.name} · ${ForecastProgress.size(file.size)}`;
      this.setParsed(parsed);
    } catch (err) {
      this.el("forecast-file").value = "";
      this.setStatus(err.name === "AbortError" ? "Reading cancelled." : `Could not read ${file.name}: ${err.message}`, true);
    } finally {
      this.busy = false;
      this.progress.stop();
      this.updateRunButton();
    }
  }

  reparse() {
    this.setParsed(ForecastInput.parse(this.input.value, this.info.max_series_length));
  }

  setParsed(parsed) {
    const previous = this.columnSelect.value;
    this.parsed = parsed;
    const { columns } = parsed;
    this.columnSelect.replaceChildren(...columns.map((c, i) => new Option(`${c.name} (${c.total.toLocaleString()} values)`, i)));
    // Keep the chosen column; else the last one (a table's first column is often an id).
    const keep = columns.findIndex((_, i) => String(i) === previous);
    if (columns.length) this.columnSelect.value = keep >= 0 ? keep : columns.length - 1;
    this.el("forecast-column-row").classList.toggle("hidden", columns.length < 2);
    this.showColumn();
  }

  /* Prepares the chosen column (gaps, order, dates) and lists what was found or fixed. */
  showColumn() {
    const column = this.parsed.columns[Number(this.columnSelect.value) || 0];
    this.prepared = column ? ForecastSeries.prepare(column, this.parsed.dates) : null;
    const hasInput = this.input.value.trim() !== "" || !this.el("forecast-file-chip").classList.contains("hidden");
    let text = hasInput ? "No numbers found. Paste numbers, or a table with a column of numbers." : "No numbers yet";
    const notes = [];
    if (this.prepared) {
      const used = this.prepared.values.length;
      text = `${used.toLocaleString()} values`;
      if (column.total > column.values.length) text += ` · the latest ${used.toLocaleString()} of ${column.total.toLocaleString()} are used`;
      if (this.prepared.step) text += ` · one every ${ForecastDates.describe(this.prepared.step)} (${this.parsed.dateName})`;
      notes.push(...this.prepared.notes);
    }
    if (this.parsed.skipped) notes.push({ text: `${this.parsed.skipped.toLocaleString()} cells were not numbers` });
    notes.push(...this.parsed.notes.map((t) => ({ text: t })));
    this.el("forecast-input-summary").textContent = text;
    this.el("forecast-input-notes").innerHTML = notes
      .map((n) => `<li class="${n.warn ? "text-warning-400" : "text-slate-500"}">${escapeHtml(n.text)}</li>`)
      .join("");
    this.updateRunButton();
  }

  /* Notes about the whole file (skipped lines, decimal commas...), for the info panel. */
  tableNotes() {
    const notes = [...this.parsed.notes];
    if (this.parsed.skipped) notes.push(`${this.parsed.skipped.toLocaleString()} cells were not numbers`);
    return notes;
  }

  updateRunButton() {
    const ready = this.prepared && this.prepared.values.length >= ForecastSeries.MIN_VALUES && this.modelSelect.value;
    this.runButton.disabled = this.busy || !ready;
  }

  async run() {
    const column = this.parsed.columns[Number(this.columnSelect.value) || 0];
    const prepared = this.prepared;
    const horizon = Math.min(Math.max(1, Number(this.horizonInput.value) || 12), Number(this.horizonInput.max) || 128);
    this.horizonInput.value = horizon;
    this.busy = true;
    this.updateRunButton();
    this.setStatus("");
    const signal = this.progress.start("Forecasting");
    this.progress.waiting("Forecasting… the first run also loads the model");
    const started = performance.now();
    try {
      const body = { model: this.modelSelect.value, series: [prepared.values], horizon };
      const reply = await ForecastRequest.send(body, signal);
      this.result = {
        history: prepared.values, prepared, name: column.name, forecast: reply.forecasts[0],
        insight: { model: body.model, column, prepared, horizon, forecast: reply.forecasts[0],
          tableNotes: this.tableNotes(),
          seconds: (performance.now() - started) / 1000 },
      };
      this.draw();
    } catch (err) {
      this.setStatus(err.name === "AbortError" ? "Forecast cancelled." : `Forecast failed: ${err.message}`, true);
    } finally {
      this.busy = false;
      this.progress.stop();
      this.updateRunButton();
    }
  }

  draw() {
    const { history, forecast, prepared } = this.result;
    this.el("forecast-result").classList.remove("hidden");
    let label = null;
    if (prepared.step) {
      const future = ForecastDates.after(prepared.dates[prepared.dates.length - 1], prepared.step, forecast.point.length);
      const at = (i) => (i < history.length ? prepared.dates[i] : future[i - history.length]);
      label = (i) => (at(i) === undefined ? "" : ForecastDates.format(at(i), prepared.step));
    }
    this.chart.render(history, forecast, label);
    this.view.renderTable(this.result);
    this.insights.render(this.result.insight);
  }

  setStatus(text, isError = false) {
    this.status.textContent = text;
    this.status.classList.toggle("hidden", !text);
    this.status.classList.toggle("text-warning-400", isError);
    this.status.classList.toggle("text-slate-500", !isError);
  }
}

new ForecastPage();
