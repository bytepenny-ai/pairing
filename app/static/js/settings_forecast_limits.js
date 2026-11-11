/* Admin settings > Models > Forecasting models > limits form: max file size and time limit, for every pAIring server of a ring (GET/PUT /api/settings/forecast-limits). */
class ForecastLimitsForm {
  static URL = "/api/settings/forecast-limits";

  constructor(form) {
    this.form = form;
    this.maxFile = form.querySelector("#forecast-max-file-mb");
    this.timeLimit = form.querySelector("#forecast-time-limit");
    this.status = form.querySelector("#forecast-limits-status");
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      this.save();
    });
    this.load();
  }

  async load() {
    try {
      this.show(await api(ForecastLimitsForm.URL));
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  show(limits) {
    this.maxFile.value = limits.max_file_mb;
    this.timeLimit.value = limits.time_limit_seconds;
  }

  async save() {
    this.status.textContent = "Saving…";
    try {
      const body = { max_file_mb: Number(this.maxFile.value), time_limit_seconds: Number(this.timeLimit.value) };
      this.show(await api(ForecastLimitsForm.URL, { method: "PUT", body: JSON.stringify(body) }));
      this.status.textContent = "Saved";
    } catch (err) {
      this.status.textContent = `Not saved: ${err.message}`;
    }
  }
}

const forecastLimitsFormEl = document.getElementById("forecast-limits-form");
PageViews.whenShown(forecastLimitsFormEl, () => new ForecastLimitsForm(forecastLimitsFormEl)); // on its page's first showing
