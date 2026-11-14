/* How the Knowledge page's file browser draws its items (settings_knowledge_files.js): folder and file cards, 5 a
 * row on a wide screen, or list rows, each file with its type, size, chunks, date, whether it can be searched, and
 * Move/Delete (disabled while the knowledge base is off). */
// Tinted, with coloured text (not white): the colour scales flip in light themes, so a solid badge with white text
// turned pale there.
const KB_TYPE_COLORS = {
  pdf: "bg-red-500/15 text-red-400",
  docx: "bg-brand-500/15 text-brand-400",
  odt: "bg-brand-500/15 text-brand-400",
  md: "bg-emerald-500/15 text-emerald-400",
  csv: "bg-amber-500/15 text-amber-400",
  json: "bg-amber-500/15 text-amber-400",
};
const KB_STATES = {
  ready: ["bg-emerald-500", "Ready", "Searchable in your chats."],
  outdated: ["bg-amber-500", "Updating", "Embedded with an older model; it is embedded again at the next sync."],
  empty: ["bg-red-500", "No text", "No text was found in it (a scanned PDF?), so chats can't search it."],
};

class KnowledgeView {
  constructor(editable, selected) {
    this.editable = editable;
    this.selected = selected; // ids of the ticked files
  }

  /* The file's name, opening it in the file viewer (chat_file_viewer.js), as a chat attachment does. */
  link(f, classes) {
    return `<a href="${this.url(f)}" data-chat-file="${escapeHtml(f.name)}" title="${escapeHtml(f.name)}" class="${classes} hover:text-brand-400 hover:underline">${escapeHtml(f.name)}</a>`;
  }

  url(f) {
    return `/api/knowledge/files/${encodeURIComponent(f.id)}`;
  }

  check(f) {
    const on = this.selected.has(f.id) ? " checked" : "";
    return `<input type="checkbox" data-kb-select="${escapeHtml(f.id)}" aria-label="Select ${escapeHtml(f.name)}" class="h-4 w-4 shrink-0 accent-brand-500"${on}${this.editable ? "" : " disabled"}>`;
  }

  cards(folders, files) {
    const card = "group flex min-w-0 flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3";
    const folderCards = folders.map(
      (f) => `<button type="button" data-kb-open="${escapeHtml(f.id)}" class="${card} text-left hover:border-brand-500">
        <span class="text-2xl leading-none">📁</span>
        <span class="truncate text-sm font-medium text-slate-100" title="${escapeHtml(f.name)}">${escapeHtml(f.name)}</span>
        <span class="text-xs text-slate-500">${f.file_count} file${f.file_count === 1 ? "" : "s"}</span>
      </button>`,
    );
    const fileCards = files.map(
      (f) => `<div class="${card}">
        <div class="flex items-center justify-between gap-2"><span class="flex items-center gap-2">${this.check(f)}${this.typeBadge(f)}</span>${this.stateDot(f)}</div>
        ${this.link(f, "truncate text-sm font-medium text-slate-100")}
        <span class="text-xs text-slate-500">${this.size(f.size_bytes)} · ${f.chunk_count} chunk${f.chunk_count === 1 ? "" : "s"}</span>
        <span class="text-xs text-slate-500">${this.date(f.created_at)}</span>
        <div class="mt-auto flex flex-wrap gap-1 pt-1">${this.actions(f)}</div>
      </div>`,
    );
    return `<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">${[...folderCards, ...fileCards].join("")}</div>`;
  }

  list(folders, files) {
    const row = "flex items-center gap-3 px-3 py-2";
    const folderRows = folders.map(
      (f) => `<button type="button" data-kb-open="${escapeHtml(f.id)}" class="${row} w-full text-left hover:bg-slate-800">
        <span class="w-4"></span><span class="w-10 text-center">📁</span><span class="min-w-0 flex-1 truncate text-sm text-slate-100">${escapeHtml(f.name)}</span>
        <span class="text-xs text-slate-500">${f.file_count} file${f.file_count === 1 ? "" : "s"}</span></button>`,
    );
    const fileRows = files.map(
      (f) => `<div class="${row}">${this.check(f)}${this.typeBadge(f)}
        ${this.link(f, "min-w-0 flex-1 truncate text-sm text-slate-100")}
        <span class="hidden w-20 text-right text-xs text-slate-500 sm:block">${this.size(f.size_bytes)}</span>
        <span class="hidden w-20 text-right text-xs text-slate-500 md:block">${f.chunk_count} chunk${f.chunk_count === 1 ? "" : "s"}</span>
        <span class="hidden w-24 text-right text-xs text-slate-500 md:block">${this.date(f.created_at)}</span>
        ${this.stateDot(f)}<div class="flex gap-1">${this.actions(f)}</div></div>`,
    );
    return `<div class="divide-y divide-slate-800 rounded-lg border border-slate-800 bg-slate-900">${[...folderRows, ...fileRows].join("")}</div>`;
  }

  typeBadge(f) {
    const color = KB_TYPE_COLORS[f.extension] || "bg-slate-500/15 text-slate-300";
    return `<span class="w-10 shrink-0 rounded px-1 py-0.5 text-center text-[10px] font-semibold uppercase ${color}">${escapeHtml(f.extension || "file")}</span>`;
  }

  stateDot(f) {
    const [color, label, about] = KB_STATES[f.state] || KB_STATES.ready;
    return `<span class="inline-flex shrink-0 items-center gap-1 text-[11px] text-slate-400" title="${escapeHtml(about)}"><span class="h-2 w-2 rounded-full ${color}"></span>${label}</span>`;
  }

  actions(f) {
    const btn = "rounded-md border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 transition-colors disabled:opacity-40";
    const off = this.editable ? "" : " disabled";
    return `<a href="${this.url(f)}" data-chat-file="${escapeHtml(f.name)}" class="${btn} hover:bg-slate-800">View</a>
      <button type="button" data-kb-move="${escapeHtml(f.id)}" class="${btn} hover:bg-slate-800"${off}>Move</button>
      <button type="button" data-kb-delete="${escapeHtml(f.id)}" class="${btn} hover:border-red-500 hover:text-red-400"${off}>Delete</button>`;
  }

  size(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  date(iso) {
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
}
