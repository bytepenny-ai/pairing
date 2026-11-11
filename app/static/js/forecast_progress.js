/* Forecast page progress: a bar for reading a file (percent of bytes) and a running timer while the model works
   (no percent is known then; a segment slides). Each run gets a fresh AbortController for its Cancel button. */
class ForecastProgress {
  constructor(root) {
    this.root = root;
    this.label = root.querySelector("[data-progress-label]");
    this.detail = root.querySelector("[data-progress-detail]");
    this.bar = root.querySelector("[data-progress-bar]");
    this.cancelButton = root.querySelector("[data-progress-cancel]");
    this.controller = null;
    this.timer = null;
    this.cancelButton.addEventListener("click", () => this.controller && this.controller.abort());
  }

  /* Shows the bar and returns the AbortSignal its Cancel button fires. */
  start(label) {
    this.stop();
    this.controller = new AbortController();
    this.label.textContent = label;
    this.detail.textContent = "";
    this.setPercent(0);
    this.root.classList.remove("hidden");
    return this.controller.signal;
  }

  bytes(done, total) {
    this.setPercent(total ? (100 * done) / total : 100);
    this.detail.textContent = `${ForecastProgress.size(done)} of ${ForecastProgress.size(total)}`;
  }

  /* The model is working: no percent is known, so a short segment slides across while the time counts. */
  waiting(label) {
    this.label.textContent = label;
    this.bar.style.width = "";
    this.bar.classList.add("forecast-indeterminate");
    const started = performance.now();
    const tick = () => (this.detail.textContent = ForecastProgress.clock((performance.now() - started) / 1000));
    tick();
    this.timer = setInterval(tick, 1000);
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.controller = null;
    this.bar.classList.remove("forecast-indeterminate");
    this.root.classList.add("hidden");
  }

  setPercent(percent) {
    this.bar.classList.remove("forecast-indeterminate");
    this.bar.style.width = `${Math.min(100, percent).toFixed(1)}%`;
  }

  static size(bytes) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit++;
    }
    return `${value.toFixed(unit ? 1 : 0)} ${units[unit]}`;
  }

  static clock(seconds) {
    const s = Math.floor(seconds);
    const h = Math.floor(s / 3600);
    const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, "0");
    const ss = String(s % 60).padStart(2, "0");
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }
}
