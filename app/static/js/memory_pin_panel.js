/**
 * Memory pinning page: the selected node's panel (its memory, model slots, pins and the "Pin a model" form).
 * Saving goes through `onSave(node, tags, everywhere)` (memory_pin_page.js), which returns a promise.
 */

const PIN_STATE_STYLE = {
  loaded: "border-emerald-700/60 text-emerald-300",
  loading: "border-amber-700/60 text-amber-300",
  failed: "border-red-700/60 text-red-300",
  unloaded: "border-slate-700 text-slate-400",
};

const PIN_MEMORY_LABEL = { auto: "Auto", vram: "GPU VRAM", ram: "CPU RAM" };

/** A pin as Matricxon saves it: "tag", "tag|ram" or "tag|vram" (auto needs no suffix). */
function pinEntry(tag, wish) {
  return wish && wish !== "auto" ? `${tag}|${wish}` : tag;
}

/** 256 MB, 2.5 GB, 26 GB, 36.9 TB. */
function pinGb(bytes) {
  const gb = bytes / 1024 ** 3;
  if (gb < 1) return `${Math.round(gb * 1024)} MB`;
  if (gb >= 1000) return `${(gb / 1024).toFixed(1)} TB`;
  return `${gb.toFixed(gb < 10 ? 1 : 0)} GB`;
}

class MemoryPinPanel {
  constructor(el) {
    this.el = el;
    this.onSave = null;  // (node, tags, addedEverywhere) => Promise<message>
    this.refresh = null;  // () => void: redraw after a save
    this.onUnload = null;  // (node, tag) => Promise<message>
    this.message = null;
    el.addEventListener("click", (e) => this._click(e));
  }

  /** `scope`: "single", "servers" (several, each with its own models) or "cluster" (every node shares them). */
  render(node, scope) {
    // Not while a control here is in use (the page redraws every few seconds): it would close a list.
    if (this.node && this.node.id === node.id && this.el.contains(document.activeElement) && !this.saving) {
      this.node = node;
      return;
    }
    this.node = node;
    const esc = (s) => escapeHtml(String(s));
    const live = node.status === "up" && node.supported !== false;
    const bar = (label, pool, mem) => {
      if (!pool || !pool.total) return `<p class="text-xs text-slate-500">${label}: ${pool ? "unknown" : "none on this server"}</p>`;
      const used = pool.total - PinMemory.free(node, mem);
      return `<div><div class="flex justify-between text-xs"><span class="text-slate-400">${label}${pool.device ? ` · ${esc(pool.device)}` : ""}</span>
        <span class="text-slate-300">${pinGb(used)} of ${pinGb(pool.total)}</span></div>
        <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800"><div class="h-full bg-slate-500" style="width:${(used / pool.total) * 100}%"></div></div></div>`;
    };
    const memorySelect = (m) => `<select data-pin-memory="${esc(m.tag)}" ${live ? "" : "disabled"} aria-label="Memory for ${esc(m.tag)}"
        title="Where it loads" class="rounded border border-slate-700 bg-slate-950 px-1 py-0.5 text-[11px] text-slate-300">
        ${Object.entries(PIN_MEMORY_LABEL).map(([k, v]) => `<option value="${k}" ${(m.wish || "auto") === k ? "selected" : ""}>${v}</option>`).join("")}</select>`;
    // Two lines: the name, its state and unpin; then size, where it is now and (GPU servers) where it should load.
    const row = (m) => `<li class="space-y-1 px-3 py-2"><div class="flex items-center gap-2">
        <span class="min-w-0 flex-1 truncate text-slate-200" title="${esc(m.tag)}">${esc(pinShortName(m.tag))}</span>
        ${m.pinned ? `<span class="shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase ${PIN_STATE_STYLE[m.state]}">${m.state}${m.state === "loading" && m.attempt ? ` ${m.attempt}/3` : ""}</span>
        <button type="button" data-unpin="${esc(m.tag)}" ${live ? "" : "disabled"} title="Unpin" aria-label="Unpin ${esc(m.tag)}" class="text-slate-500 hover:text-slate-200 disabled:opacity-40">&times;</button>` : ""}</div>
        <div class="flex items-center gap-2 text-slate-500"><span class="flex-1">${pinGb(m.bytes)} · in ${m.memory === "vram" ? "VRAM" : "RAM"}${!m.pinned && m.expires_in != null ? ` · unloads in ${pinWait(m.expires_in)}` : ""}</span>
        ${!m.pinned ? `<button type="button" data-unload="${esc(m.tag)}" ${live ? "" : "disabled"} title="Unload it now"
          class="rounded border border-slate-700 px-1.5 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">Unload</button>` : ""}
        ${m.pinned && node.vram ? memorySelect(m) : ""}</div>
        ${m.error ? `<p class="text-[11px] text-warning-400">${esc(m.error)}</p>` : ""}</li>`;
    const pins = node.models.filter((m) => m.pinned), demand = node.models.filter((m) => !m.pinned);
    const list = (items, empty) => (items.length
      ? `<ul class="divide-y divide-slate-800 rounded-lg border border-slate-800 bg-slate-950 text-xs">${items.map(row).join("")}</ul>`
      : `<p class="text-xs text-slate-500">${empty}</p>`);
    const pinned = new Set(pins.map((m) => m.tag));
    this.entries = pins.map((m) => pinEntry(m.tag, m.wish));
    const autoText = node.runs_on === "gpu" ? "Auto (VRAM if it fits)" : "Auto (RAM: runs on the CPU)";
    // Every installed model, by group; the pinned ones stay listed, greyed out.
    const installed = node.installed || [];
    const choices = installed.filter((m) => !pinned.has(m.tag));
    const groups = Object.keys(PIN_KIND_LABEL).map((g) => [g, installed.filter((m) => pinGroup(m) === g)]).filter(([, list]) => list.length);
    const options = groups.map(([g, list]) => `<optgroup label="${PIN_KIND_LABEL[g]}">${list.map((m) => `<option value="${esc(m.tag)}" title="${esc(m.tag)}"
      ${pinned.has(m.tag) ? "disabled" : ""}>${esc(pinShortName(m.tag))} · ${pinGb(m.ram_bytes || m.bytes)}${pinned.has(m.tag) ? " · pinned" : ""}</option>`).join("")}</optgroup>`).join("");
    const why = node.status !== "up" ? "This server does not answer."
      : node.supported === false ? "This Matricxon has no pins yet: update it first." : "";
    this.el.innerHTML = `
      <div><p class="text-sm font-medium text-slate-100">${esc(node.name)}
        <span class="ml-1 text-xs font-normal ${node.status === "up" ? "text-emerald-400" : "text-red-400"}">${node.status}</span></p>
        <p class="font-mono text-xs text-slate-500">${esc(node.address.replace("http://", ""))}</p></div>
      ${bar("CPU RAM", node.ram, "ram")}${bar("GPU VRAM", node.vram, "vram")}
      <p class="text-xs text-slate-400">Model slots: <span class="text-slate-200">${node.slots.used} of ${node.slots.max}</span>
        <span class="text-slate-500">(pinned chat models count)</span></p>
      <div class="space-y-1.5"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Pinned models</p>
        ${list(pins, "No pins: models load when a chat needs them.")}</div>
      <form data-pin-form class="space-y-2 rounded-lg border border-dashed border-slate-700 p-3">
        <label class="block text-xs text-slate-400" for="pin-choice">Pin a model</label>
        <div class="flex items-center gap-2 text-xs">
          <select id="pin-choice" ${live && choices.length ? "" : "disabled"} class="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300">
            ${installed.length ? options : "<option>No installed models</option>"}</select>
          <button type="submit" ${live && choices.length ? "" : "disabled"} class="rounded-md bg-brand-600 px-3 py-1 text-white hover:bg-brand-500 disabled:opacity-50">Pin</button>
        </div>
        <p data-pin-facts class="text-[11px] leading-snug text-slate-500"></p>
        ${node.vram ? `<label class="flex items-center gap-2 text-xs text-slate-400">Memory
          <select id="pin-memory" ${live ? "" : "disabled"} class="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300">
            <option value="auto">${autoText}</option><option value="vram">GPU VRAM</option><option value="ram">CPU RAM</option></select></label>`
          : `<p class="text-[11px] text-slate-500">Loads into CPU RAM (no GPU on this server).</p>`}
        ${scope !== "single" ? `<label class="flex items-center gap-1.5 text-xs text-slate-400"><input type="checkbox" data-pin-everywhere ${live ? "" : "disabled"} class="rounded border-slate-600 bg-slate-950">
          ${scope === "cluster" ? "Pin on every Matricxon cluster node" : "Pin on every server that has it installed"}</label>` : ""}
        ${why ? `<p class="text-[11px] text-slate-500">${why}</p>` : ""}
      </form>
      <p data-pin-message class="${this.message ? "" : "hidden"} text-xs ${this.message && this.message.error ? "text-warning-400" : "text-emerald-400"}">${this.message ? esc(this.message.text) : ""}</p>
      <div class="space-y-1.5"><p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Loaded on demand</p>
        ${list(demand, "None right now.")}</div>`;
    const form = this.el.querySelector("[data-pin-form]");
    // The chosen model's details under the list, again when the model or the memory changes.
    const showFacts = () => {
      const model = choices.find((m) => m.tag === form.querySelector("#pin-choice").value);
      const facts = form.querySelector("[data-pin-facts]");
      if (!model) return facts.classList.add("hidden");
      const memory = form.querySelector("#pin-memory");
      const { text, fits } = pinFacts(model, node, memory ? memory.value : "auto");
      facts.textContent = text;
      facts.classList.remove("hidden");
      facts.classList.toggle("text-warning-400", !fits);
      facts.classList.toggle("text-slate-500", fits);
    };
    form.querySelector("#pin-choice").addEventListener("change", showFacts);
    form.querySelector("#pin-memory")?.addEventListener("change", showFacts);
    showFacts();
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const everywhere = Boolean(form.querySelector("[data-pin-everywhere]:checked"));
      const memory = form.querySelector("#pin-memory");
      const added = pinEntry(form.querySelector("#pin-choice").value, memory ? memory.value : "auto");
      this._save([...this.entries, added], everywhere, added);
    });
    this.el.querySelectorAll("[data-pin-memory]").forEach((select) => select.addEventListener("change", () => {
      const tag = select.dataset.pinMemory;
      this._save(pins.map((m) => (m.tag === tag ? pinEntry(tag, select.value) : pinEntry(m.tag, m.wish))), false, null);
    }));
  }

  _click(event) {
    const unload = event.target.closest("[data-unload]");
    if (unload && !unload.disabled) {
      const tag = unload.dataset.unload;
      if (confirm(`Unload ${pinShortName(tag)} now? A reply using it right now is stopped; it loads again when a chat needs it.`)) {
        this._run(() => this.onUnload(this.node, tag));
      }
      return;
    }
    const button = event.target.closest("[data-unpin]");
    if (!button || button.disabled) return;
    const tags = this.node.models.filter((m) => m.pinned && m.tag !== button.dataset.unpin).map((m) => pinEntry(m.tag, m.wish));
    this._save(tags, false, null);
  }

  async _save(tags, everywhere, added) {
    return this._run(() => this.onSave(this.node, [...new Set(tags)], everywhere ? added : null));
  }

  /** One change on the node: controls off and a note meanwhile, then its message and a redraw. */
  async _run(change) {
    this.saving = true;
    this.el.querySelectorAll("button, select, input").forEach((x) => (x.disabled = true));
    const note = this.el.querySelector("[data-pin-message]");
    note.textContent = "Working on the server… (slower while a model loads).";
    note.className = "text-xs text-slate-400";
    try {
      this.message = { text: await change(), error: false };
    } catch (error) {
      this.message = { text: error.message, error: true };
    }
    if (this.refresh) this.refresh();  // the page redraws with the node's new record
    this.saving = false;
  }
}
