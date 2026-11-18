/* While a message with files or knowledge excerpts is being read, its user bubble is swapped for a small vector space:
   dots drifting around the origin, the question as a pink dot, and its nearest dots (by the angle seen from the
   origin) lit up. The dots only show that a search runs; the numbers are real: the best search score of the excerpts
   sent (bestMatch) and the prompt's read progress. A canvas drawn at ~30 fps; stops when removed.
   chat_reply_stream.js: cover() on send with files or on a "retrieval" event, bestMatch() with it, progress() on
   "read_progress", reveal() at the first words or when the send ends. */
class VectorSpace {
  static SIZE = 132; // CSS px, square
  static DOTS = 26;
  static FRAME_MS = 33;

  /* Hides `wrapper`'s bubble behind the animation, or updates the one already there. */
  static cover(wrapper, kind, count) {
    if (!wrapper) return null;
    const existing = wrapper._vectorSpace;
    if (existing) {
      existing.add(kind, count);
      return existing;
    }
    const bubble = wrapper.querySelector(".markdown-body");
    if (!bubble) return null;
    wrapper._vectorSpace = new VectorSpace(bubble, kind, count);
    return wrapper._vectorSpace;
  }

  /* The best similarity score among the excerpts sent (the same score as under Sources); null: unknown. */
  static bestMatch(wrapper, score) {
    const space = wrapper?._vectorSpace;
    if (!space || typeof score !== "number") return;
    space.best = score;
    if (space.still) space.draw(0);
  }

  static progress(wrapper, fraction) {
    const space = wrapper?._vectorSpace;
    if (!space) return;
    space.fraction = Math.max(0, Math.min(1, fraction));
    if (space.still) space.draw(0); // reduced motion: redraw only on news
  }

  /* Puts the bubble back (its text and attachments). Safe to call when nothing is covered. */
  static reveal(wrapper) {
    if (!wrapper?._vectorSpace) return;
    wrapper._vectorSpace.close();
    wrapper._vectorSpace = null;
  }

  constructor(bubble, kind, count) {
    this.bubble = bubble;
    this.kinds = {};
    this.fraction = null;
    this.best = null;
    this.box = document.createElement("div");
    this.box.className = "vector-space";
    this.box.setAttribute("role", "status");
    this.canvas = document.createElement("canvas");
    this.label = document.createElement("span");
    this.label.className = "vector-space-label text-slate-400";
    this.score = document.createElement("span");
    this.score.className = "vector-space-label vector-space-score text-slate-400";
    this.box.append(this.canvas, this.label, this.score);
    bubble.classList.add("hidden");
    bubble.after(this.box);
    this.add(kind, count);
    this.colors = this.readColors();
    this.dots = Array.from({ length: VectorSpace.DOTS }, () => this.randomDot());
    this.fit();
    this.still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    this.start = performance.now();
    this.last = 0;
    this.tick = this.tick.bind(this);
    requestAnimationFrame(this.tick);
  }

  add(kind, count) {
    this.kinds[kind] = Math.max(this.kinds[kind] || 0, count || 1);
    const parts = [];
    if (this.kinds.files) parts.push(`${this.kinds.files} file${this.kinds.files > 1 ? "s" : ""}`);
    if (this.kinds.knowledge) parts.push("knowledge");
    this.what = parts.join(" + ");
    this.label.textContent = this.what;
    this.nearest = Math.min(6, Math.max(3, (this.kinds.knowledge || 0) + (this.kinds.files || 0)));
    this.box.setAttribute("aria-label", `Reading ${this.what}`);
  }

  /* Theme colors from the CSS variables ("R G B"), read once per cover. */
  readColors() {
    const style = getComputedStyle(this.box);
    const rgb = (name, fallback) => (style.getPropertyValue(name).trim() || fallback).split(/\s+/).join(",");
    return {
      dot: rgb("--color-slate-500", "100 116 139"), // grays follow the theme
      hit: rgb("--color-slate-400", "148 163 184"), // strong gray, not black, in light themes
      query: rgb("--color-warn-pink-400", "244 114 182"), // the only color, faded
      axis: rgb("--color-slate-600", "71 85 105"),
    };
  }

  randomDot() {
    const angle = Math.random() * Math.PI * 2;
    return { angle, radius: 0.25 + Math.random() * 0.7, speed: 0.06 + Math.random() * 0.12, phase: Math.random() * 6.3 };
  }

  fit() {
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    this.canvas.width = this.canvas.height = VectorSpace.SIZE * ratio;
    this.ctx = this.canvas.getContext("2d");
    this.ctx.scale(ratio, ratio);
  }

  tick(now) {
    if (!this.box.isConnected) return; // removed with the chat (a switch rebuilds #messages)
    if (!this.still) requestAnimationFrame(this.tick);
    if (now - this.last < VectorSpace.FRAME_MS && !this.still) return;
    this.last = now;
    this.draw((now - this.start) / 1000);
  }

  /* One frame at `t` seconds: dots flow around the origin, nearest ones to the question glow. */
  draw(t) {
    const { ctx, colors } = this;
    const size = VectorSpace.SIZE;
    const half = size / 2;
    const reach = half - 10;
    ctx.clearRect(0, 0, size, size);
    ctx.strokeStyle = `rgba(${colors.axis},0.25)`;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(6, half);
    ctx.lineTo(size - 6, half);
    ctx.moveTo(half, 6);
    ctx.lineTo(half, size - 6);
    ctx.stroke();
    ctx.setLineDash([]);

    const qAngle = t * 0.35 + Math.sin(t * 0.7) * 0.6;
    const query = { x: half + Math.cos(qAngle) * reach * 0.55, y: half + Math.sin(qAngle) * reach * 0.55 };
    const points = this.dots.map((dot) => {
      const angle = dot.angle + t * dot.speed;
      const radius = reach * (dot.radius + Math.sin(t * 0.8 + dot.phase) * 0.05);
      // Cosine similarity of the two vectors from the origin is the cosine of the angle between them.
      return { x: half + Math.cos(angle) * radius, y: half + Math.sin(angle) * radius, cos: Math.cos(angle - qAngle) };
    });
    const ranked = [...points].sort((a, b) => b.cos - a.cos);
    const near = new Set(ranked.slice(0, this.nearest));

    const sweep = (t * 0.6) % 1; // a search ring widening from the question
    ctx.strokeStyle = `rgba(${colors.query},${0.3 * (1 - sweep)})`;
    ctx.beginPath();
    ctx.arc(query.x, query.y, 6 + sweep * reach * 0.7, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = `rgba(${colors.hit},0.3)`;
    ctx.beginPath();
    for (const p of near) {
      ctx.moveTo(query.x, query.y);
      ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();

    for (const p of points) {
      const hit = near.has(p);
      ctx.fillStyle = hit ? `rgba(${colors.hit},0.9)` : `rgba(${colors.dot},${0.4 + 0.4 * Math.max(0, p.cos)})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, hit ? 3.2 : 2.2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.strokeStyle = `rgba(${colors.query},0.35)`; // the question's vector from the origin
    ctx.beginPath();
    ctx.moveTo(half, half);
    ctx.lineTo(query.x, query.y);
    ctx.stroke();
    ctx.fillStyle = `rgba(${colors.query},0.6)`;
    ctx.shadowColor = `rgba(${colors.query},0.4)`;
    ctx.shadowBlur = 5;
    ctx.beginPath();
    ctx.arc(query.x, query.y, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    this.drawProgress(t);
    const parts = [];
    if (this.best != null) parts.push(`best match ${this.best.toFixed(2)}`);
    if (this.fraction != null) parts.push(`${Math.floor(this.fraction * 100)}%`);
    this.score.textContent = parts.join(" · ");
  }

  /* Bottom bar: the prompt's read progress when known, else a sliding glow. */
  drawProgress(t) {
    const { ctx, colors } = this;
    const size = VectorSpace.SIZE;
    const y = size - 3;
    ctx.fillStyle = `rgba(${colors.axis},0.2)`;
    ctx.fillRect(8, y, size - 16, 2);
    ctx.fillStyle = `rgba(${colors.hit},0.6)`;
    if (this.fraction != null) ctx.fillRect(8, y, (size - 16) * this.fraction, 2);
    else ctx.fillRect(8 + ((t * 0.5) % 1) * (size - 46), y, 30, 2);
  }

  close() {
    this.box.remove();
    this.bubble.classList.remove("hidden");
    this.bubble.classList.add("vector-space-reveal");
  }
}
