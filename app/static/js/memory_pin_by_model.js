/**
 * Memory pinning page, several servers: "Pins across the cluster", one row per pinned model with the servers that pin
 * it. Up to INLINE servers are named in the row; more open from the server count (a link) as chips colored by the pin's state. A click on
 * a server opens it in the node panel (`onSelect`, memory_pin_page.js). Open rows stay open across live updates.
 */
class PinsByModel {
  static #INLINE = 3;
  static #DOT = { loaded: "bg-emerald-400", loading: "bg-amber-400", failed: "bg-red-400", unloaded: "bg-slate-500", down: "bg-slate-600" };

  constructor(tbody) {
    this.tbody = tbody;
    this.open = new Set();
    this.onSelect = null;
    tbody.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-pin-servers]");
      if (toggle) {
        const tag = toggle.dataset.pinServers;
        if (!this.open.delete(tag)) this.open.add(tag);
        this.render(this.snap);
        return;
      }
      const server = event.target.closest("[data-pin-node]");
      if (server) this.onSelect?.(server.dataset.pinNode);
    });
  }

  render(snap) {
    this.snap = snap;
    const rows = {};
    for (const node of snap.nodes) {
      for (const m of node.models.filter((x) => x.pinned)) {
        const r = (rows[m.tag] ||= { tag: m.tag, bytes: m.bytes, servers: [], loaded: 0, vram: 0, missing: 0 });
        const state = node.status === "up" ? m.state : "down";
        r.servers.push({ id: node.id, name: node.name, state });
        if (state === "loaded") r.loaded += 1; else r.missing += 1;
        if (m.memory === "vram" && state === "loaded") r.vram += 1; // not on a server that is down
      }
    }
    const sorted = Object.values(rows).sort((a, b) => b.servers.length - a.servers.length || a.tag.localeCompare(b.tag));
    this.tbody.innerHTML = sorted.length
      ? sorted.map((r) => this.#row(r)).join("")
      : `<tr><td colspan="6" class="px-3 py-3 text-slate-500">No pins yet.</td></tr>`;
  }

  #row(r) {
    const few = r.servers.length <= PinsByModel.#INLINE;
    const isOpen = this.open.has(r.tag);
    const on = few
      ? `<span class="inline-flex flex-wrap gap-x-3 gap-y-1">${r.servers.map((s) => this.#server(s, false)).join("")}</span>`
      : `<button type="button" data-pin-servers="${escapeHtml(r.tag)}" aria-expanded="${isOpen}" title="${isOpen ? "Hide" : "Show"} the servers"
          class="inline-flex items-center gap-1 text-brand-400 underline decoration-dotted underline-offset-2 hover:text-brand-300">${r.servers.length} servers
          <span class="inline-block transition-transform ${isOpen ? "rotate-180" : ""}" aria-hidden="true">&#9662;</span></button>`;
    const main = `<tr><td class="px-3 py-2 text-slate-200" title="${escapeHtml(r.tag)}">${escapeHtml(pinShortName(r.tag))}</td>
      <td class="px-3 py-2 text-slate-400">${pinGb(r.bytes)}</td><td class="px-3 py-2 text-slate-300">${on}</td>
      <td class="px-3 py-2 text-emerald-400">${r.loaded}</td><td class="px-3 py-2 text-slate-400">${r.vram}</td>
      <td class="px-3 py-2 ${r.missing ? "text-warning-400" : "text-slate-500"}">${r.missing}</td></tr>`;
    if (few || !isOpen) return main;
    // Not loaded first: those are the ones to look at.
    const order = (s) => (s.state === "loaded" ? 1 : 0);
    const chips = [...r.servers].sort((a, b) => order(a) - order(b) || a.name.localeCompare(b.name, undefined, { numeric: true }));
    return `${main}<tr class="bg-slate-900/40"><td colspan="6" class="px-3 pb-3 pt-1">
      <div class="flex flex-wrap gap-1.5">${chips.map((s) => this.#server(s, true)).join("")}</div></td></tr>`;
  }

  #server(s, chip) {
    const label = s.state === "down" ? "server down" : s.state;
    const look = chip ? "rounded-full border border-slate-800 bg-slate-950 px-2 py-0.5" : "underline decoration-dotted underline-offset-2";
    return `<button type="button" data-pin-node="${escapeHtml(s.id)}" title="${escapeHtml(s.name)}: ${label}. Click to open it."
      class="inline-flex items-center gap-1.5 ${look} text-slate-300 hover:text-slate-100 ${chip ? "hover:bg-slate-800" : ""}">
      <span class="h-1.5 w-1.5 shrink-0 rounded-full ${PinsByModel.#DOT[s.state] || PinsByModel.#DOT.unloaded}"></span>${escapeHtml(s.name)}</button>`;
  }
}
