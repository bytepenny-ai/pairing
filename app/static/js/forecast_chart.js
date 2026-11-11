/* Forecast page chart (d3): the recent history, the forecast median and its 10%-90% and 30%-70% bands. */
class ForecastChart {
  static HISTORY_SHOWN = 200; // the latest points drawn; older ones would squash the forecast

  constructor(svgEl) {
    this.svg = d3.select(svgEl);
  }

  /* `label(i)`: the x-axis text for history index i (future steps continue past the end), or null for numbers. */
  render(history, forecast, label = null) {
    const shown = history.slice(-ForecastChart.HISTORY_SHOWN);
    const start = history.length - shown.length;
    const past = shown.map((y, i) => ({ x: start + i, y }));
    const next = forecast.point.map((y, i) => ({
      x: history.length + i,
      y,
      q1: forecast.quantiles["0.1"][i],
      q9: forecast.quantiles["0.9"][i],
      q3: forecast.quantiles["0.3"][i],
      q7: forecast.quantiles["0.7"][i],
    }));
    // Join the median line to the last real value so the two lines meet.
    const last = past[past.length - 1];
    const joined = [{ x: last.x, y: last.y, q1: last.y, q9: last.y, q3: last.y, q7: last.y }, ...next];

    const { g, width, height } = this.frame();
    const x = d3.scaleLinear().domain([past[0].x, next[next.length - 1].x]).range([0, width]);
    const ys = [...past.map((p) => p.y), ...next.flatMap((p) => [p.q1, p.q9])];
    const y = d3.scaleLinear().domain(d3.extent(ys)).nice().range([height, 0]);
    this.axes(g, x, y, height, label);

    const band = (lo, hi) => d3.area().x((d) => x(d.x)).y0((d) => y(d[lo])).y1((d) => y(d[hi]));
    const line = d3.line().x((d) => x(d.x)).y((d) => y(d.y));
    const brand = ThemeColors.chart(1);
    g.append("path").datum(joined).attr("d", band("q1", "q9")).attr("fill", brand).attr("fill-opacity", 0.15);
    g.append("path").datum(joined).attr("d", band("q3", "q7")).attr("fill", brand).attr("fill-opacity", 0.25);
    g.append("path").datum(past).attr("d", line).attr("fill", "none")
      .attr("stroke", ThemeColors.get("--color-slate-400")).attr("stroke-width", 1.5);
    g.append("path").datum(joined).attr("d", line).attr("fill", "none")
      .attr("stroke", brand).attr("stroke-width", 2);
    g.append("line").attr("x1", x(last.x)).attr("x2", x(last.x)).attr("y1", 0).attr("y2", height)
      .attr("stroke", ThemeColors.get("--color-slate-600")).attr("stroke-dasharray", "3 3");
  }

  frame() {
    const node = this.svg.node();
    const box = node.getBoundingClientRect();
    const margin = { top: 10, right: 12, bottom: 24, left: 48 };
    const outerWidth = Math.max(box.width, 320);
    const outerHeight = 280;
    this.svg.selectAll("*").remove();
    this.svg.attr("viewBox", `0 0 ${outerWidth} ${outerHeight}`);
    const g = this.svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
    return { g, width: outerWidth - margin.left - margin.right, height: outerHeight - margin.top - margin.bottom };
  }

  axes(g, x, y, height, label) {
    const color = ThemeColors.get("--color-slate-500");
    const ticks = label ? Math.max(2, Math.floor(x.range()[1] / 110)) : 6; // dates need more room
    const format = label ? (i) => label(Math.round(i)) : d3.format("d");
    g.append("g").attr("transform", `translate(0,${height})`)
      .call(d3.axisBottom(x).ticks(ticks).tickFormat(format)).attr("color", color).attr("font-size", "10px");
    g.append("g").call(d3.axisLeft(y).ticks(5).tickFormat(d3.format("~s"))).attr("color", color)
      .attr("font-size", "10px");
  }
}
