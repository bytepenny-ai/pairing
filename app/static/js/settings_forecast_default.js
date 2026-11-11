/* Admin settings > Models > Default models: the default forecasting model (app/templates/_forecast_model.html, /api/settings/forecast-model). Uses api from app.js. */
class ForecastDefaultSetting {
  static URL = "/api/settings/forecast-model";

  constructor(root) {
    this.select = root.querySelector("#forecast-default-model");
    this.note = root.querySelector("#forecast-default-model-note");
    this.saveBtn = root.querySelector("#forecast-default-model-save-btn");
    this.status = root.querySelector("#forecast-default-model-status");
    this.saveBtn.addEventListener("click", () => this.save());
    this.load();
  }

  render(setting) {
    this.select.replaceChildren(...setting.installed.map((tag) => new Option(tag, tag)));
    if (setting.model) this.select.value = setting.model;
    const note = !setting.engine_supports
      ? "The active engine can't forecast. Forecasting works with Matricxon."
      : setting.installed.length
        ? ""
        : "No forecasting model installed. Pull one under Manage models > Forecasting models.";
    this.note.textContent = note;
    this.note.classList.toggle("hidden", !note);
    this.select.disabled = this.saveBtn.disabled = !setting.installed.length;
  }

  async load() {
    try {
      this.render(await api(ForecastDefaultSetting.URL));
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  async save() {
    this.status.textContent = "Saving…";
    try {
      this.render(await api(ForecastDefaultSetting.URL, { method: "PUT", body: JSON.stringify({ model: this.select.value }) }));
      this.status.textContent = "Saved";
    } catch (err) {
      this.status.textContent = `Not saved: ${err.message}`;
    }
  }
}

const forecastDefaultPanelEl = document.getElementById("forecast-default-panel");
PageViews.whenShown(forecastDefaultPanelEl, () => new ForecastDefaultSetting(forecastDefaultPanelEl)); // on its page's first showing
