/**
 * Admin settings > Inference > Memory pinning (settings/memory_pinning.html): totals, the memory grid
 * (memory_pin_grid.js), the selected node's panel (memory_pin_panel.js) and, with several servers, pins by model.
 * Live data from every Matricxon server (memory_pin_live.js), read every PIN_LIVE_MS while shown.
 */

const PIN_LIVE_MS = 3000;

class MemoryPinPage {
  constructor(root) {
    this.root = root;
    this.grid = new MemoryGrid(root.querySelector("#pin-grid"), root.querySelector("#pin-tooltip"));
    this.grid.onSelect = (id) => this.select(id);
    this.panel = new MemoryPinPanel(root.querySelector("#pin-node"));
    this.panel.refresh = () => this.render();
    this.live = new MemoryPinLive();
    this.selected = null;
    this.started = false;
    this._timer = null;
    this.panel.onSave = (node, tags, everywhere) => this._save(node, tags, everywhere);
    this.panel.onUnload = async (node, tag) => {
      await this.live.unload(node.address, tag);
      return `Unloaded ${pinShortName(tag)}.`;
    };
    root.querySelectorAll("[data-pin-view]").forEach((b) => b.addEventListener("click", () => this.setView(b.dataset.pinView)));
    root.querySelector("#pin-search").addEventListener("input", (e) => {
      this.grid.filter = e.target.value.trim().toLowerCase();
      this.grid.draw();
    });
    root.querySelector("#pin-motion").addEventListener("change", (e) => {
      this.grid.motion = e.target.checked;
      this.grid.draw();
    });
  }

  get snapshot() {
    return this.live.snapshot;
  }

  /** The first read: picks the first server and the view (both memories when a server has a GPU). */
  async start() {
    this.started = true;
    await this._read();
    this._schedule();  // also after a failed first read: the next one may answer
    const snap = this.snapshot;
    if (!snap || !snap.nodes.length) return this.render();
    this.selected = snap.nodes[0].id;
    this.setView(snap.nodes.some((n) => n.vram) ? "both" : "ram");
  }

  setView(view) {
    this.grid.view = view;
    this.root.querySelectorAll("[data-pin-view]").forEach((b) => this._mark(b, b.dataset.pinView === view));
    this.render();
  }

  _mark(button, on) {
    button.classList.toggle("bg-slate-800", on);
    button.classList.toggle("text-slate-100", on);
  }

  setActive(active) {
    this.active = active;
    this.grid.setActive(active);
    if (active && !this.started) return this.start();
    this._schedule();
    if (active && this.snapshot) this.render();
  }

  _schedule() {
    clearInterval(this._timer);
    this._timer = this.active ? setInterval(() => this._tick(), PIN_LIVE_MS) : null;
  }

  async _read() {
    try {
      const events = await this.live.fetch();
      this._status("");
      return events;
    } catch (error) {
      this._status(error.message);
      return [];
    }
  }

  async _tick() {
    if (document.hidden || this._busy) return;
    this._busy = true;
    const events = await this._read();
    this._busy = false;
    this.render();
    if (this.snapshot && this.snapshot.nodes.length) this.grid.spawn(events);
  }

  /** One node, or (`everywhere`: the pin just added, "tag" or "tag|vram") every server with it installed; a server
   * without a GPU gets it as auto (RAM). Returns the message shown. */
  async _save(node, tags, everywhere) {
    await this.live.save(node.address, tags);
    if (!everywhere) return "Saved on this server. Pinned models load in the background.";
    const tag = everywhere.split("|")[0];
    const others = this.live.snapshot.nodes.filter((n) => n.id !== node.id && n.status === "up" && n.supported !== false
      && n.installed.some((m) => m.tag === tag) && !n.models.some((m) => m.pinned && m.tag === tag));
    const failed = [];
    for (const other of others) {
      const pins = other.models.filter((m) => m.pinned).map((m) => pinEntry(m.tag, m.wish));
      try {
        await this.live.save(other.address, [...pins, other.vram ? everywhere : tag]);
      } catch (error) {
        failed.push(`${other.name}: ${error.message}`);
      }
    }
    const word = this.snapshot.scope === "cluster" ? "node" : "server";
    if (failed.length) throw new Error(`Pinned on ${others.length + 1 - failed.length} ${word}s. Not on ${failed.join("; ")}`);
    return `Pinned on ${others.length + 1} ${word}${others.length ? "s" : ""}.`;
  }

  _status(text) {
    const el = this.root.querySelector("#pin-status");
    el.textContent = text;
    el.classList.toggle("hidden", !text);
  }

  select(id) {
    if (id !== this.selected) this.panel.message = null;
    this.selected = id;
    this.render();
  }

  render() {
    const snap = this.snapshot;
    const off = !this.live.supported;
    this.root.querySelector("#pin-engine-off").classList.toggle("hidden", !off);
    const none = !off && (!snap || !snap.nodes.length);
    this.root.querySelector("#pin-body").classList.toggle("hidden", off || none);
    // Only a message: the width of the other settings pages; the grid gets the wide layout.
    this.root.classList.toggle("max-w-[55.2rem]", off || none);
    this.root.classList.toggle("max-w-6xl", !(off || none));
    if (off || none) {
      this.root.querySelector("#pin-scope").classList.add("hidden");
      return this._status(none ? "No Matricxon server to show yet." : "");
    }
    const many = snap.scope !== "single";
    const n = snap.nodes.length, s = n === 1 ? "" : "s";
    const label = { single: "single server", servers: `${n} server${s}`, cluster: `cluster · ${n} node${s}` };
    this.root.querySelector("#pin-scope").textContent = label[snap.scope] || label.cluster;
    this.root.querySelector("#pin-scope").classList.remove("hidden");
    this.root.querySelector("#pin-search").classList.toggle("hidden", !many);
    this.root.querySelector("#pin-by-model").classList.toggle("hidden", !many);
    this.grid.selected = this.selected;
    this.grid.update(snap);
    this.root.querySelector("#pin-unit").textContent = `1 cell = ${pinGb(this.grid.unit).replace(".0 ", " ")} of memory`;
    this._renderTiles(snap);
    const node = snap.nodes.find((n) => n.id === this.selected) || snap.nodes[0];
    this.panel.render(node, snap.scope);
    if (many) this._renderByModel(snap);
  }

  _renderTiles(snap) {
    const up = snap.nodes.filter((n) => n.status === "up");
    const sum = (f) => up.reduce((s, n) => s + f(n), 0);
    const pins = up.flatMap((n) => n.models.filter((m) => m.pinned));
    const pinned = (mem) => sum((n) => n.models.filter((m) => m.pinned && m.memory === mem && PinMemory.holds(m)).reduce((s, m) => s + m.bytes, 0));
    const ramTotal = sum((n) => n.ram.total), vramTotal = sum((n) => (n.vram ? n.vram.total : 0));
    const gpus = up.filter((n) => n.vram).length;
    const failed = pins.filter((m) => m.state === "failed").length;
    const tile = (label, value, sub, used = null, pin = null) => `
      <div class="rounded-lg border border-slate-800 bg-slate-900 px-4 py-3">
        <p class="text-[11px] font-medium uppercase tracking-wide text-slate-500">${label}</p>
        <p class="mt-1 text-lg font-semibold text-slate-100">${value}</p>
        <p class="text-xs text-slate-500">${sub}</p>
        ${used === null ? "" : `<div class="mt-2 flex h-1.5 overflow-hidden rounded-full bg-slate-800">
          <span class="bg-brand-500" style="width:${pin}%"></span><span class="bg-slate-500" style="width:${Math.max(0, used - pin)}%"></span></div>`}
      </div>`;
    const pct = (part, total) => (total ? Math.round((part / total) * 100) : 0);
    const ramUsed = sum((n) => n.ram.total - PinMemory.free(n, "ram"));
    const vramUsed = sum((n) => (n.vram ? n.vram.total - PinMemory.free(n, "vram") : 0));
    const first = up[0];
    this.root.querySelector("#pin-tiles").innerHTML = [
      tile("CPU RAM", pinGb(ramTotal), `${pinGb(pinned("ram"))} pinned · ${pinGb(ramTotal - ramUsed)} free`, pct(ramUsed, ramTotal), pct(pinned("ram"), ramTotal)),
      vramTotal
        ? tile("GPU VRAM", pinGb(vramTotal), `${pinGb(pinned("vram"))} pinned · ${gpus} GPU${gpus === 1 ? "" : "s"}`, pct(vramUsed, vramTotal), pct(pinned("vram"), vramTotal))
        : tile("GPU VRAM", "No GPU", "pins load into CPU RAM"),
      tile("Pins", `${pins.filter((m) => m.state === "loaded").length} of ${pins.length} loaded`, failed ? `<span class="text-warning-400">${failed} could not load</span>` : pins.length ? "all pins healthy" : "none yet"),
      snap.scope !== "single"
        ? tile("Servers", `${up.length} of ${snap.nodes.length} up`, `${sum((n) => n.slots.max)} model slots in all`)
        : tile("Model slots", first ? `${first.slots.used} of ${first.slots.max} used` : "server down", "pinned chat models count"),
    ].join("");
  }

  _renderByModel(snap) {
    const rows = {};
    for (const node of snap.nodes) {
      for (const m of node.models.filter((x) => x.pinned)) {
        const r = (rows[m.tag] ||= { tag: m.tag, bytes: m.bytes, on: 0, loaded: 0, vram: 0, missing: 0 });
        r.on += 1;
        if (node.status === "up" && m.state === "loaded") r.loaded += 1; else r.missing += 1;
        if (m.memory === "vram" && m.state === "loaded") r.vram += 1;
      }
    }
    const sorted = Object.values(rows).sort((a, b) => b.on - a.on);
    this.root.querySelector("#pin-by-model-rows").innerHTML = sorted.length
      ? sorted.map((r) => `<tr><td class="px-3 py-2 text-slate-200" title="${escapeHtml(r.tag)}">${escapeHtml(pinShortName(r.tag))}</td><td class="px-3 py-2 text-slate-400">${pinGb(r.bytes)}</td>
          <td class="px-3 py-2 text-slate-300">${r.on} server${r.on === 1 ? "" : "s"}</td><td class="px-3 py-2 text-emerald-400">${r.loaded}</td>
          <td class="px-3 py-2 text-slate-400">${r.vram}</td><td class="px-3 py-2 ${r.missing ? "text-warning-400" : "text-slate-500"}">${r.missing}</td></tr>`).join("")
      : `<tr><td colspan="6" class="px-3 py-3 text-slate-500">No pins yet.</td></tr>`;
  }
}

const memoryPinRoot = document.getElementById("tab-memory-pinning");
const memoryPinPage = memoryPinRoot ? new MemoryPinPage(memoryPinRoot) : null;
// A reload can restore this tab before this file loads (settings.js restoreTabAfterReload): start it here then.
if (memoryPinPage && !memoryPinRoot.classList.contains("hidden")) memoryPinPage.setActive(true);
