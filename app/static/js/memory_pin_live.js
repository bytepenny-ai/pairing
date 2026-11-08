/**
 * Memory pinning page: live data from GET /api/settings/memory-pins (services/memory_pins.py; its shape is in
 * memory_pin_common.js) and pin saving (PUT, one node's whole list). Movements for the grid's dots come from comparing
 * one read with the one before: a model that appears loaded, disappears, or appears on a second node (a warm-up).
 */

class MemoryPinLive {
  constructor() {
    this.snapshot = null;
    this.supported = true;
  }

  /** Reads the nodes; returns the movements since the last read. Throws on a failed request. */
  async fetch() {
    const resp = await fetch("/api/settings/memory-pins");
    if (!resp.ok) throw new Error(`Could not read the servers (${resp.status})`);
    const data = await resp.json();
    this.supported = data.supported;
    const before = this.snapshot;
    this.snapshot = { scope: data.scope, nodes: data.nodes };
    return before ? MemoryPinLive.movements(before, this.snapshot) : [];
  }

  /** Load, unload and warm-up events between two snapshots. */
  static movements(before, after) {
    const held = (snap) => {
      const map = new Map();
      for (const node of snap.nodes) {
        for (const m of node.models) if (PinMemory.holds(m)) map.set(`${node.id}|${m.tag}`, { node: node.id, model: m });
      }
      return map;
    };
    const was = held(before), now = held(after);
    const events = [];
    for (const [key, { node, model }] of now) {
      if (was.has(key)) continue;
      const from = [...was.values()].find((x) => x.model.tag === model.tag && x.node !== node);
      events.push(from
        ? { kind: "warm", node, memory: model.memory, tag: model.tag, from: from.node }
        : { kind: "load", node, memory: model.memory, tag: model.tag });
    }
    for (const [key, { node, model }] of was) {
      if (!now.has(key)) events.push({ kind: "unload", node, memory: model.memory, tag: model.tag });
    }
    return events;
  }

  /** Saves one node's whole pin list on the node; returns its fresh record. Throws with the node's reason. */
  async save(address, tags) {
    return this._send("PUT", "/api/settings/memory-pins", { address, pinned_models: tags });
  }

  /** Unloads a model that is not pinned, now; returns the node's fresh record. */
  async unload(address, tag) {
    return this._send("POST", "/api/settings/memory-pins/unload", { address, tag });
  }

  async _send(method, url, body) {
    const resp = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(typeof data.detail === "string" ? data.detail : `The server answered ${resp.status}`);
    const i = this.snapshot.nodes.findIndex((n) => n.id === data.id);
    if (i >= 0) this.snapshot.nodes[i] = data;
    return data;
  }
}
