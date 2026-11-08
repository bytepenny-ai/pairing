/**
 * Memory pinning page: the data shape every part draws (from GET /api/settings/memory-pins, services/memory_pins.py):
 *   { scope: "single" | "servers" | "cluster",
 *     nodes: [{ id, name, address, status: "up" | "down", slots: { used, max }, supported, runs_on,
 *               installed: [{ tag, bytes, ram_bytes, kind: "chat" | "embedding" | "rerank", capabilities, family,
 *                             context_length }],
 *               ram: { total, other },                  // bytes; other = used by the system and other programs
 *               vram: { total, other, device } | null,  // null: no GPU
 *               models: [{ tag, bytes, memory: "ram" | "vram", pinned, state, attempt, error }] }] }
 *   state: "loaded" | "loading" | "failed" | "unloaded" (failed and unloaded pins hold no memory).
 * Movements for the grid's dots: [{ kind: "load" | "unload" | "warm", node, memory, tag, from? }].
 */

class PinMemory {
  /** A model that takes memory now. */
  static holds(model) {
    return model.state === "loaded" || model.state === "loading";
  }

  /** Free bytes of one memory of a node. */
  static free(node, memory) {
    const pool = node[memory];
    if (!pool) return 0;
    const used = node.models.filter((m) => m.memory === memory && PinMemory.holds(m)).reduce((s, m) => s + m.bytes, 0);
    return Math.max(0, pool.total - pool.other - used);
  }
}

/** A readable model name: "hf.co/unsloth/gemma-4-E2B-it-GGUF:gemma-4-E2B-it-Q4_K_M" -> "gemma-4-E2B-it-Q4_K_M";
 * a file named only by its quantization keeps the repository: "all-MiniLM-L6-v2 (Q8_0)". */
function pinShortName(tag) {
  if (!tag.startsWith("hf.co/")) return tag;
  const [path, file = ""] = tag.split(":");
  const repo = path.split("/").pop().replace(/-GGUF$/i, "");
  if (!file) return repo;
  if (repo.toLowerCase().endsWith(file.toLowerCase())) return repo;
  return file.toLowerCase().startsWith(repo.slice(0, 6).toLowerCase()) ? file : `${repo} (${file})`;
}

const PIN_KIND_LABEL = { chat: "Chat models", vision: "Vision models", embedding: "Embedding models", rerank: "Reranking models" };

/** The list group of an installed model: a chat model that reads images is a vision model. */
function pinGroup(model) {
  return model.kind === "chat" && model.capabilities.includes("vision") ? "vision" : model.kind;
}

/** One line about an installed model: kind, features, family, context, the memory it needs and whether it fits. */
function pinFacts(model, node, memory) {
  const k = (n) => (n >= 1024 ? `${Math.round(n / 1024)}K` : `${n}`);
  const needs = model.ram_bytes || model.bytes;
  const where = memory === "vram" || (memory === "auto" && node.runs_on === "gpu" && node.vram) ? "vram" : "ram";
  const free = PinMemory.free(node, where);
  const parts = [
    { chat: "Chat", vision: "Vision", embedding: "Embedding", rerank: "Reranking" }[pinGroup(model)] || "Chat",
    model.capabilities.filter((c) => c !== "vision" || pinGroup(model) !== "vision").join(", "),
    model.family,
    model.context_length ? `${k(model.context_length)} context` : "",
    `needs about ${pinGb(needs)}`,
    free >= needs ? `fits (${pinGb(free)} ${where === "vram" ? "VRAM" : "RAM"} free)` : `more than the ${pinGb(free)} ${where === "vram" ? "VRAM" : "RAM"} free now`,
    model.kind === "chat" ? "takes a model slot" : "no model slot",
  ];
  return { text: parts.filter(Boolean).join(" · "), fits: free >= needs };
}

/** "45 s", "12 min", "23 h", "2 d": how long until a keep-alive unloads a model. */
function pinWait(seconds) {
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}
