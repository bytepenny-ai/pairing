/**
 * Memory pinning page: the square memory grid (canvas). One square per node, sized by its memory, packed into one
 * square; each cell is a fixed amount of memory (MemoryGrid.unit). Dots move along the grid lines for loads,
 * unloads and warm-ups. Animates only while shown, with Motion on and no reduced-motion preference.
 */

const PIN_UNITS = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64].map((g) => g * 1024 ** 3);
const PIN_MAX_CELLS = 12000;
const PIN_LABEL_PX = 18;

/** Theme colours, read from the CSS tokens so every theme (light or dark) gets its own. */
function pinColor(name, shade, alpha = 1) {
  const rgb = getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}-${shade}`).trim();
  return rgb ? `rgb(${rgb} / ${alpha})` : "#888";
}

class MemoryGrid {
  constructor(canvas, tooltip) {
    this.canvas = canvas;
    this.tooltip = tooltip;
    this.ctx = canvas.getContext("2d");
    this.view = "both";
    this.blocks = [];
    this.dots = [];
    this.selected = null;
    this.filter = "";
    this.motion = true;
    this.active = false;
    this.onSelect = () => {};
    this._frame = null;
    canvas.addEventListener("mousemove", (e) => this._hover(e));
    canvas.addEventListener("mouseleave", () => this.tooltip.classList.add("hidden"));
    canvas.addEventListener("click", (e) => {
      const hit = this._hit(e);
      if (hit) this.onSelect(hit.block.node.id);
    });
    new ResizeObserver(() => this.snapshot && this.update(this.snapshot)).observe(canvas.parentElement);
  }

  palette() {
    return {
      pinned: pinColor("brand", 500), demand: "#a78bfa", loading: pinColor("red", 300),
      other: pinColor("slate", 500), free: pinColor("slate", 700, 0.55), line: pinColor("slate", 950),
      text: pinColor("slate", 300), down: pinColor("red", 500), mark: pinColor("slate", 100),
    };
  }

  _memories() {
    return this.view === "both" ? ["ram", "vram"] : [this.view];
  }

  /** Bytes per cell: the smallest step that keeps the whole cluster under PIN_MAX_CELLS cells. */
  _unit(nodes) {
    const total = nodes.reduce((s, n) => s + this._memories().reduce((t, m) => t + (n[m] ? n[m].total : 0), 0), 0);
    return PIN_UNITS.find((u) => total / u <= PIN_MAX_CELLS) || PIN_UNITS[PIN_UNITS.length - 1];
  }

  update(snapshot) {
    this.snapshot = snapshot;
    const nodes = snapshot.nodes;
    this.unit = this._unit(nodes);
    const width = this.canvas.parentElement.clientWidth;
    for (let cell = 40; cell >= 3; cell--) {
      if (this._pack(nodes, cell, width) <= 640 || cell === 3) break;
    }
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = width * ratio;
    this.canvas.height = this.height * ratio;
    this.canvas.style.height = `${this.height}px`;
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.draw();
  }

  /** Shelf-packs the node squares at `cell` px per cell; returns the height used. */
  _pack(nodes, cell, width) {
    this.cell = cell;
    const gap = Math.max(4, cell);
    const label = nodes.length <= 24 && cell >= 8 ? PIN_LABEL_PX : 0;
    const blocks = nodes.map((node) => {
      const parts = this._memories().filter((m) => node[m]).map((m) => {
        const cells = Math.max(1, Math.ceil(node[m].total / this.unit));
        return { memory: m, cells, side: Math.ceil(Math.sqrt(cells)) };
      });
      const w = parts.reduce((s, p) => s + p.side * cell, 0) + gap * Math.max(0, parts.length - 1);
      const h = Math.max(cell, ...parts.map((p) => p.side * cell)) + label;
      return { node, parts, w: Math.max(w, cell), h };
    });
    blocks.sort((a, b) => b.h - a.h || b.w - a.w);
    let x = 0, y = 0, row = 0;
    for (const b of blocks) {
      if (x > 0 && x + b.w > width) { x = 0; y += row + gap; row = 0; }
      b.x = x; b.y = y; b.label = label;
      x += b.w + gap * 1.5;
      row = Math.max(row, b.h);
    }
    this.blocks = blocks;
    this.height = y + row + 2;
    return this.height;
  }

  /** The cells of one memory square, in order: pinned, loading, on demand, other, free. */
  _cells(node, memory, part) {
    const unit = this.unit;
    const held = node.models.filter((m) => m.memory === memory && PinMemory.holds(m));
    const order = (m) => (m.pinned ? (m.state === "loaded" ? 0 : 1) : 2);
    const cells = [];
    for (const m of held.sort((a, b) => order(a) - order(b))) {
      const kind = m.state === "loading" ? "loading" : m.pinned ? "pinned" : "demand";
      for (let i = 0; i < Math.max(1, Math.round(m.bytes / unit)); i++) cells.push({ kind, model: m });
    }
    for (let i = 0; i < Math.round(node[memory].other / unit); i++) cells.push({ kind: "other" });
    while (cells.length < part.cells) cells.push({ kind: "free" });
    return cells.slice(0, part.cells);
  }

  draw(now = performance.now()) {
    const ctx = this.ctx, c = this.palette(), cell = this.cell;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    const pulse = this._animating() ? 0.55 + 0.45 * Math.sin(now / 260) : 1;
    for (const b of this.blocks) {
      const dim = this.filter && !`${b.node.name} ${b.node.address}`.toLowerCase().includes(this.filter);
      ctx.globalAlpha = dim ? 0.18 : b.node.status === "down" ? 0.35 : 1;
      if (b.label) {
        ctx.fillStyle = c.text;
        ctx.font = "11px system-ui, sans-serif";
        ctx.fillText(b.node.name, b.x, b.y + 12);
      }
      let px = b.x;
      b.cellMap = {};
      for (const part of b.parts) {
        const cells = this._cells(b.node, part.memory, part);
        b.cellMap[part.memory] = { x0: px, y0: b.y + b.label, side: part.side, cells };
        cells.forEach((cl, i) => {
          const x = px + (i % part.side) * cell, y = b.y + b.label + Math.floor(i / part.side) * cell;
          ctx.fillStyle = c[cl.kind];
          if (cl.kind === "loading") ctx.globalAlpha = (dim ? 0.18 : 1) * pulse;
          ctx.fillRect(x + 0.5, y + 0.5, cell - 1, cell - 1);
          if (cl.kind === "loading") ctx.globalAlpha = dim ? 0.18 : 1;
        });
        if (part.memory === "vram" && cell >= 8) {  // a GPU square: a thin bar on top tells it apart
          ctx.fillStyle = c.mark;
          ctx.fillRect(px, b.y + b.label - 2, part.side * cell, 1.5);
        }
        px += part.side * cell + Math.max(4, cell);
      }
      if (b.node.status === "down" || (this.selected === b.node.id && this.blocks.length > 1)) {
        ctx.strokeStyle = b.node.status === "down" ? c.down : c.mark;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(b.x - 2, b.y + b.label - 2, b.w + 4, b.h - b.label + 4);
      }
    }
    ctx.globalAlpha = 1;
    this._drawDots(now);
  }

  _animating() {
    return this.active && this.motion && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /** Centre of a model's first cell (or the square's corner), for a dot's end. */
  _point(nodeId, memory, tag) {
    const b = this.blocks.find((x) => x.node.id === nodeId);
    const map = b && b.cellMap && b.cellMap[memory];
    if (!map) return null;
    const i = Math.max(0, map.cells.findIndex((cl) => cl.model && cl.model.tag === tag));
    return { x: map.x0 + (i % map.side) * this.cell + this.cell / 2, y: map.y0 + Math.floor(i / map.side) * this.cell + this.cell / 2 };
  }

  /** Dots for each movement: in from the top edge (load), out of it (unload), node to node (warm). */
  spawn(events) {
    if (!this._animating()) return;
    const c = this.palette();
    for (const e of events.slice(0, 40)) {
      const end = this._point(e.node, e.memory, e.tag);
      if (!end) continue;
      const start = e.kind === "warm" ? this._point(e.from, e.memory, e.tag) || this._point(e.from, "ram", e.tag) : { x: end.x, y: -6 };
      if (!start) continue;
      const [a, b] = e.kind === "unload" ? [end, start] : [start, end];
      const color = e.kind === "warm" ? c.demand : e.kind === "unload" ? c.other : c.pinned;
      for (let k = 0; k < 5; k++) this.dots.push({ a, b, color, t0: performance.now() + k * 90, ms: 900 });
    }
    this._loop();
  }

  _drawDots(now) {
    this.dots = this.dots.filter((d) => now - d.t0 < d.ms);
    for (const d of this.dots) {
      const t = Math.max(0, (now - d.t0) / d.ms);
      if (t <= 0) continue;
      // Along the grid lines: across first, then down (an L-shaped path).
      const dx = Math.abs(d.b.x - d.a.x), dy = Math.abs(d.b.y - d.a.y), run = (dx + dy) * t;
      const x = run < dx ? d.a.x + Math.sign(d.b.x - d.a.x) * run : d.b.x;
      const y = run < dx ? d.a.y : d.a.y + Math.sign(d.b.y - d.a.y) * (run - dx);
      this.ctx.fillStyle = d.color;
      this.ctx.beginPath();
      this.ctx.arc(x, y, Math.max(2, this.cell / 4), 0, Math.PI * 2);
      this.ctx.fill();
    }
  }

  /** Redraws each frame while dots move or pins load; stops when nothing moves. */
  _loop() {
    if (this._frame || !this._animating()) return;
    const step = (now) => {
      this._frame = null;
      this.draw(now);
      const loading = this.snapshot && this.snapshot.nodes.some((n) => n.models.some((m) => m.state === "loading"));
      if (this._animating() && (this.dots.length || loading)) this._frame = requestAnimationFrame(step);
    };
    this._frame = requestAnimationFrame(step);
  }

  setActive(active) {
    this.active = active;
    if (active) this._loop(); else this.dots = [];
  }

  _hit(event) {
    const r = this.canvas.getBoundingClientRect(), x = event.clientX - r.left, y = event.clientY - r.top;
    for (const block of this.blocks) {
      for (const [memory, map] of Object.entries(block.cellMap || {})) {
        const col = Math.floor((x - map.x0) / this.cell), row = Math.floor((y - map.y0) / this.cell);
        if (col < 0 || row < 0 || col >= map.side) continue;
        const cl = map.cells[row * map.side + col];
        if (cl) return { block, memory, cell: cl };
      }
    }
    return null;
  }

  _hover(event) {
    const hit = this._hit(event);
    this.canvas.style.cursor = hit ? "pointer" : "default";
    if (!hit) return this.tooltip.classList.add("hidden");
    const where = hit.memory === "vram" ? "GPU VRAM" : "CPU RAM";
    const m = hit.cell.model;
    const what = m ? `${m.tag} · ${(m.bytes / 1024 ** 3).toFixed(1)} GB · ${m.pinned ? `pinned (${m.state})` : "loaded on demand"}`
      : { other: "used by the system", free: "free" }[hit.cell.kind];
    this.tooltip.textContent = `${hit.block.node.name} · ${where} · ${what}`;
    this.tooltip.style.left = `${event.offsetX + 14}px`;
    this.tooltip.style.top = `${event.offsetY + 14}px`;
    this.tooltip.classList.remove("hidden");
  }
}
