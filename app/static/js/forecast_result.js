/* Forecast page: POST /api/forecast's streamed reply (ForecastRequest) and the result table and CSV (ForecastResultView). */
class ForecastRequest {
  /* Resolves to the ForecastRunResponse; heartbeat lines only keep the connection alive. No time limit here: the
     admin's limit (if any) is enforced by the server, which then sends an "error" line. */
  static async send(body, signal) {
    const response = await fetch("/api/forecast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (response.status === 401) {
      window.location.href = "/login";
      throw new Error("Not authenticated");
    }
    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = formatErrorDetail((await response.json()).detail);
      } catch (_) {
        /* not JSON: keep statusText */
      }
      throw new Error(detail);
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines.filter(Boolean)) {
        const event = JSON.parse(line);
        if (event.type === "result") return event.result;
        if (event.type === "error") throw new Error(event.detail);
      }
    }
    throw new Error("The server closed the connection before the forecast finished.");
  }
}

class ForecastResultView {
  constructor(tableBody) {
    this.tableBody = tableBody;
  }

  /* The label of each forecast step: its date when the data has dates, else its row number. */
  static labels({ history, forecast, prepared }) {
    const { dates, step } = prepared;
    if (!step) return forecast.point.map((_, i) => String(history.length + i + 1));
    return ForecastDates.after(dates[dates.length - 1], step, forecast.point.length).map((d) => ForecastDates.format(d, step));
  }

  renderTable(result) {
    const { forecast } = result;
    const labels = ForecastResultView.labels(result);
    const fmt = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
    this.tableBody.closest("table").querySelector("[data-step-head]").textContent = result.prepared.step ? "Date" : "Step";
    this.tableBody.innerHTML = forecast.point
      .map(
        (p, i) =>
          `<tr class="border-t border-slate-800"><td class="py-1 pr-4 text-slate-500 whitespace-nowrap">${escapeHtml(labels[i])}</td>` +
          `<td class="py-1 pr-4">${fmt(forecast.quantiles["0.1"][i])}</td>` +
          `<td class="py-1 pr-4 font-medium text-slate-100">${fmt(p)}</td>` +
          `<td class="py-1">${fmt(forecast.quantiles["0.9"][i])}</td></tr>`
      )
      .join("");
  }

  /* The forecast as CSV: step, median, mean and every quantile. */
  download(result) {
    if (!result) return;
    const { forecast } = result;
    const labels = ForecastResultView.labels(result);
    const levels = Object.keys(forecast.quantiles);
    const lines = [[result.prepared.step ? "date" : "step", "median", "mean", ...levels.map((q) => `q${q}`)].join(",")];
    forecast.point.forEach((p, i) => {
      lines.push([labels[i], p, forecast.mean[i], ...levels.map((q) => forecast.quantiles[q][i])].join(","));
    });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], { type: "text/csv" }));
    link.download = `forecast-${result.name.replace(/[^\w-]+/g, "_")}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }
}
