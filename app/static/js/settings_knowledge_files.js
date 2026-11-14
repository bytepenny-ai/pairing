/* Settings > Knowledge's file browser (settings/knowledge.html #knowledge-browser, /api/knowledge): the user's files at
 * the top level or in a folder, as cards (5 a row on a wide screen) or a list (the choice is remembered in this
 * browser), with Move and Delete per file or for the ticked ones together (the selection bar), folder
 * New/Rename/Delete, and Add files, which opens the upload form in a
 * floating window (#kb-upload-modal; uploading itself is settings.js handleUpload, into `folderId`). */
const KB_VIEW_KEY = "pairing.knowledgeView";
class KnowledgeBrowser {
  constructor(root, dialog, uploadModal) {
    this.root = root;
    this.dialog = dialog;
    this.uploadModal = uploadModal;
    this.field = (name) => root.querySelector(`[data-kb="${name}"]`);
    this.folderId = null; // null: the top level
    this.folders = [];
    this.files = [];
    this.selected = new Set(); // ids of the ticked files in this view
    this.view = this.savedView();
    this.field("new-folder").addEventListener("click", () => this.newFolder());
    this.field("rename-folder").addEventListener("click", () => this.renameFolder());
    this.field("delete-folder").addEventListener("click", () => this.deleteFolder());
    this.field("add-files").addEventListener("click", () => this.openUpload());
    uploadModal.querySelector('[data-kb="close-upload"]').addEventListener("click", () => this.closeUpload());
    uploadModal.addEventListener("click", (event) => event.target === uploadModal && this.closeUpload());
    for (const btn of root.querySelectorAll("[data-kb-view]")) {
      btn.addEventListener("click", () => this.setView(btn.dataset.kbView));
    }
    this.field("content").addEventListener("click", (event) => this.onContentClick(event));
    this.field("content").addEventListener("change", (event) => this.onTick(event));
    if (typeof ChatFileViewer !== "undefined") new ChatFileViewer().attach(this.field("content")); // View, a file's name
    this.field("select-all").addEventListener("click", () => this.selectAll());
    this.field("clear-selection").addEventListener("click", () => this.clearSelection());
    this.field("move-selected").addEventListener("click", () => this.moveFiles(this.chosen()));
    this.field("delete-selected").addEventListener("click", () => this.deleteFiles(this.chosen()));
    PageViews.whenShown(document.getElementById("tab-knowledge"), () => this.reload());
  }

  get folder() {
    return this.folders.find((f) => f.id === this.folderId) || null;
  }

  get editable() {
    return typeof ragAvailable === "undefined" || ragAvailable;
  }

  async reload() {
    try {
      const [folders, files] = await Promise.all([
        api("/api/knowledge/folders"),
        api(`/api/knowledge/files${this.folderId ? `?folder_id=${encodeURIComponent(this.folderId)}` : ""}`),
      ]);
      this.folders = folders;
      this.files = files;
      const here = new Set(files.map((f) => f.id));
      this.selected = new Set([...this.selected].filter((id) => here.has(id))); // gone ones drop out
      this.status("");
    } catch (err) {
      if (this.folderId) return this.open(null); // the folder is gone (deleted elsewhere): back to the top level
      this.status(`Could not load your files: ${err.message}`, true);
    }
    this.render();
  }

  open(folderId) {
    this.folderId = folderId;
    this.selected.clear();
    return this.reload();
  }

  render() {
    const inFolder = Boolean(this.folder);
    const crumbs = this.field("crumbs");
    crumbs.innerHTML = inFolder
      ? `<button type="button" data-kb-open="" class="hover:text-brand-400 hover:underline">My files</button><span class="text-slate-600">/</span><span class="truncate font-medium text-slate-100">${escapeHtml(this.folder.name)}</span>`
      : `<span class="font-medium text-slate-100">My files</span>`;
    crumbs.querySelector("[data-kb-open]")?.addEventListener("click", () => this.open(null));
    this.field("new-folder").classList.toggle("hidden", inFolder);
    this.field("rename-folder").classList.toggle("hidden", !inFolder);
    this.field("delete-folder").classList.toggle("hidden", !inFolder);
    for (const name of ["new-folder", "rename-folder", "delete-folder", "add-files"]) this.field(name).disabled = !this.editable;
    for (const btn of this.root.querySelectorAll("[data-kb-view]")) {
      const on = btn.dataset.kbView === this.view;
      btn.classList.toggle("bg-brand-600", on); // brand, not slate: slate shades flip in light themes
      btn.classList.toggle("text-white", on);
    }
    this.renderSelection();
    const folders = inFolder ? [] : this.folders;
    const content = this.field("content");
    if (!folders.length && !this.files.length) {
      content.innerHTML = `<p class="rounded-lg border border-dashed border-slate-700 px-4 py-8 text-center text-xs text-slate-500">${
        inFolder ? "This folder is empty. Add files here, or move files in from the top level." : "No documents yet. Add files to let your chats search them."
      }</p>`;
      return;
    }
    const view = new KnowledgeView(this.editable, this.selected);
    content.innerHTML = this.view === "list" ? view.list(folders, this.files) : view.cards(folders, this.files);
  }

  onContentClick(event) {
    const target = event.target.closest("[data-kb-open], [data-kb-move], [data-kb-delete]");
    if (!target || target.disabled) return;
    if (target.dataset.kbOpen !== undefined) return this.open(target.dataset.kbOpen || null);
    const file = this.files.find((f) => f.id === (target.dataset.kbMove || target.dataset.kbDelete));
    if (file && target.dataset.kbMove) this.moveFiles([file]);
    else if (file) this.deleteFiles([file]);
  }

  onTick(event) {
    const id = event.target.dataset?.kbSelect;
    if (!id) return;
    if (event.target.checked) this.selected.add(id);
    else this.selected.delete(id);
    this.renderSelection();
  }

  renderSelection() {
    const count = this.selected.size;
    this.field("selection").classList.toggle("hidden", !count);
    this.field("selected-count").textContent = `${count} file${count === 1 ? "" : "s"} selected`;
    this.field("select-all").classList.toggle("hidden", count === this.files.length);
    for (const name of ["move-selected", "delete-selected"]) this.field(name).disabled = !this.editable;
  }

  selectAll() {
    this.selected = new Set(this.files.map((f) => f.id));
    this.render();
  }

  clearSelection() {
    this.selected.clear();
    this.render();
  }

  chosen() {
    return this.files.filter((f) => this.selected.has(f.id));
  }

  /* One file or several: its name in the dialog, or how many. */
  named(files) {
    return files.length === 1 ? `"${files[0].name}"` : `${files.length} files`;
  }

  async moveFiles(files) {
    const options = [{ value: "", label: "My files (top level)" }, ...this.folders.map((f) => ({ value: f.id, label: f.name }))]
      .filter((o) => (o.value || null) !== this.folderId);
    if (!options.length) return this.status("Create a folder first, then move files into it.");
    const file_ids = files.map((f) => f.id);
    const moved = await this.dialog.ask({
      title: `Move ${this.named(files)}`, text: "To:", ok: "Move", options,
      submit: (folderId) => this.send("/api/knowledge/files/move", "POST", { file_ids, folder_id: folderId || null }),
    });
    if (moved) await this.reload();
  }

  async deleteFiles(files) {
    const file_ids = files.map((f) => f.id);
    const done = await this.dialog.ask({
      title: `Delete ${this.named(files)}?`, ok: "Delete", danger: true,
      text: `Your chats will no longer find anything in ${files.length === 1 ? "it" : "them"}.`,
      submit: () => this.send("/api/knowledge/files/delete", "POST", { file_ids }),
    });
    if (done) await Promise.all([this.reload(), typeof loadKnowledgeSummary === "function" ? loadKnowledgeSummary() : null]);
  }

  async newFolder() {
    let made = null;
    const done = await this.dialog.ask({
      title: "New folder", ok: "Create", input: { placeholder: "Folder name" },
      submit: async (name) => {
        made = await api("/api/knowledge/folders", { method: "POST", body: JSON.stringify({ name }) });
      },
    });
    if (done) await this.open(made.id);
  }

  async renameFolder() {
    const done = await this.dialog.ask({
      title: "Rename folder", ok: "Rename", input: { value: this.folder.name },
      submit: (name) => this.send(`/api/knowledge/folders/${encodeURIComponent(this.folderId)}`, "PUT", { name }),
    });
    if (done) await this.reload();
  }

  async deleteFolder() {
    const count = this.files.length;
    const done = await this.dialog.ask({
      title: `Delete the folder "${this.folder.name}"?`, ok: "Delete folder", danger: true,
      text: count ? `Its ${count} file${count === 1 ? "" : "s"} move to the top level; no file is deleted.` : "It is empty.",
      submit: () => this.send(`/api/knowledge/folders/${encodeURIComponent(this.folderId)}`, "DELETE"),
    });
    if (done) await this.open(null);
  }

  /* Calls the API; an error comes back as the dialog's message (null when it went through). */
  async send(path, method, body) {
    await api(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
    return null;
  }

  openUpload() {
    const where = this.folder ? `Into the folder "${this.folder.name}".` : "Into My files (the top level).";
    this.uploadModal.querySelector('[data-kb="upload-target"]').textContent = where;
    this.uploadModal.classList.remove("hidden");
  }

  closeUpload() {
    this.uploadModal.classList.add("hidden"); // an upload in progress carries on, and the list reloads when it ends
  }

  setView(view) {
    this.view = view;
    try {
      localStorage.setItem(KB_VIEW_KEY, view);
    } catch (_err) {
      // Storage blocked: the choice lasts until the page reloads.
    }
    this.render();
  }

  savedView() {
    try {
      return localStorage.getItem(KB_VIEW_KEY) === "list" ? "list" : "cards";
    } catch (_err) {
      return "cards";
    }
  }

  status(text, warn = false) {
    const el = this.field("status");
    el.textContent = text;
    el.classList.toggle("text-warning-400", warn);
  }
}

const knowledgeBrowserRoot = document.getElementById("knowledge-browser");
const knowledgeBrowser = knowledgeBrowserRoot
  ? new KnowledgeBrowser(
      knowledgeBrowserRoot,
      new KnowledgeDialog(document.getElementById("kb-dialog")),
      document.getElementById("kb-upload-modal"),
    )
  : undefined;
