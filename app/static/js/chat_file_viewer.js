/**
 * Chat file viewer: a click on an image or a file in a message opens it in a soft floating window (75% of the screen).
 * Images show as pictures, PDFs in the browser's own PDF viewer (as text where there is none, as on phones), other
 * documents as their text (GET /api/chat/attachments/{id}/preview; Markdown rendered). Download saves the file.
 * Closes with the × button, a click outside it, or Escape. Ctrl/Cmd+click still opens the file in a new tab.
 */
class ChatFileViewer {
  static #FADE_MS = 180;
  static #IMAGES = [".png", ".jpg", ".jpeg", ".gif", ".webp"];
  static #DOCUMENTS = [".pdf", ".txt", ".md", ".csv", ".json", ".docx", ".odt", ".rtf", ".html", ".htm"];

  static #suffix(name) {
    const dot = (name || "").lastIndexOf(".");
    return dot < 0 ? "" : name.slice(dot).toLowerCase();
  }

  static #LOCAL_LIMIT = 200_000; // characters of a just-sent file shown before "the preview ends here"

  /* A just-sent text file read from its blob: URL; Word and PDF files need the server's text extraction. */
  static async #localPreview(url, root) {
    const name = root.querySelector("[data-viewer-name]").textContent;
    const suffix = ChatFileViewer.#suffix(name);
    if (![".txt", ".md", ".csv", ".json", ".html"].includes(suffix)) {
      throw new Error("The preview is ready once the reply has started");
    }
    const text = await (await fetch(url)).text();
    return {
      filename: name,
      format: suffix === ".md" ? "markdown" : "text",
      text: text.slice(0, ChatFileViewer.#LOCAL_LIMIT),
      truncated: text.length > ChatFileViewer.#LOCAL_LIMIT,
    };
  }

  static kindOf(name) {
    const suffix = ChatFileViewer.#suffix(name);
    if (ChatFileViewer.#IMAGES.includes(suffix)) return "image";
    if (suffix === ".pdf" && navigator.pdfViewerEnabled) return "pdf";
    return ChatFileViewer.#DOCUMENTS.includes(suffix) ? "text" : null;
  }

  /** Whether a file of this name opens in the viewer (chat.js renderAttachment); others download as before. */
  static canShow(name) {
    return ChatFileViewer.kindOf(name) !== null;
  }

  constructor() {
    this.root = null;
    this.returnFocus = null;
    this.closeTimer = null;
    this.loading = 0; // tells a late preview reply from the file now shown
  }

  /** Listens for clicks on chat images and files inside `container`. */
  attach(container) {
    if (!container) return;
    container.addEventListener("click", (event) => {
      const link = event.target.closest("a[data-chat-file]");
      if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
      event.preventDefault();
      this.open(link.getAttribute("href"), link.dataset.chatFile);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.isOpen()) this.close();
    });
  }

  isOpen() {
    return !!this.root && !this.root.classList.contains("hidden");
  }

  open(url, name) {
    this.root ??= this.#build();
    clearTimeout(this.closeTimer);
    this.returnFocus = document.activeElement;
    this.root.querySelector("[data-viewer-name]").textContent = name;
    const save = this.root.querySelector("[data-viewer-save]");
    save.href = url;
    save.download = name;
    this.#show(url, name, ChatFileViewer.kindOf(name));
    this.root.classList.remove("hidden");
    requestAnimationFrame(() => this.root.classList.add("chat-viewer-shown"));
    this.root.querySelector("[data-viewer-close]").focus();
  }

  close() {
    if (!this.isOpen()) return;
    this.loading += 1;
    this.root.classList.remove("chat-viewer-shown");
    this.closeTimer = setTimeout(() => {
      this.root.classList.add("hidden");
      this.root.querySelector("[data-viewer-body]").replaceChildren(); // stops a PDF viewer, frees a big picture
    }, ChatFileViewer.#FADE_MS);
    this.returnFocus?.focus?.();
  }

  #show(url, name, kind) {
    const body = this.root.querySelector("[data-viewer-body]");
    this.root.querySelector(".chat-viewer-panel").dataset.kind = kind;
    if (kind === "image") {
      const img = document.createElement("img");
      img.src = url;
      img.alt = name;
      img.className = "chat-viewer-img max-h-full max-w-full rounded-2xl object-contain";
      body.replaceChildren(img);
    } else if (kind === "pdf") {
      const frame = document.createElement("iframe");
      frame.src = url;
      frame.title = name;
      frame.className = "h-full w-full rounded-2xl border-0 bg-white";
      body.replaceChildren(frame);
    } else {
      body.replaceChildren(this.#note("Loading…"));
      this.#loadText(url, body);
    }
  }

  async #loadText(url, body) {
    const ticket = ++this.loading;
    let preview;
    try {
      // A file just sent still has the browser's own blob: URL (the optimistic bubble, chat.js sendMessage) until the
      // chat reloads its messages: read it here, as the server's preview isn't reachable through that URL.
      preview = url.startsWith("blob:") ? await ChatFileViewer.#localPreview(url, this.root) : await api(`${url}/preview`);
    } catch (err) {
      if (ticket === this.loading) body.replaceChildren(this.#note(`${err.message}. Use Download to open it.`));
      return;
    }
    if (ticket !== this.loading) return;
    const page = document.createElement("div");
    page.className = "chat-viewer-text h-full w-full overflow-auto rounded-2xl bg-slate-950/60 px-6 py-5 text-sm leading-relaxed text-slate-200";
    page.dir = "auto";
    if (preview.format === "markdown") {
      page.classList.add("markdown-body");
      renderMessageContent(page, preview.text); // chat.js: marked + DOMPurify, as chat replies
    } else {
      // Data (CSV, JSON) in a code font; prose (text, Word, PDF) in the page's own.
      const data = [".csv", ".json"].includes(ChatFileViewer.#suffix(preview.filename));
      const pre = document.createElement("pre");
      pre.className = "whitespace-pre-wrap break-words " + (data ? "font-mono text-[13px]" : "font-sans");
      pre.textContent = preview.text;
      page.appendChild(pre);
    }
    if (preview.truncated) page.appendChild(this.#note("The preview ends here. Download shows the whole file."));
    body.replaceChildren(page);
  }

  #note(text) {
    const p = document.createElement("p");
    p.className = "px-2 py-6 text-center text-sm text-slate-400";
    p.textContent = text;
    return p;
  }

  #build() {
    const root = document.createElement("div");
    root.className = "chat-viewer hidden fixed inset-0 z-50 flex items-center justify-center p-4";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-modal", "true");
    root.setAttribute("aria-label", "File");
    root.innerHTML = `
      <div class="chat-viewer-panel flex flex-col overflow-hidden rounded-3xl bg-slate-900/95">
        <div class="flex items-center gap-3 px-5 pt-3 pb-2">
          <span data-viewer-name dir="auto" class="min-w-0 flex-1 truncate text-sm text-slate-400"></span>
          <a data-viewer-save class="rounded-full px-3 py-1 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">Download</a>
          <button type="button" data-viewer-close aria-label="Close" title="Close (Esc)"
            class="flex h-8 w-8 items-center justify-center rounded-full text-lg leading-none text-slate-400 hover:bg-slate-800 hover:text-slate-200">&times;</button>
        </div>
        <div data-viewer-body class="flex min-h-0 flex-1 items-center justify-center px-5 pb-5"></div>
      </div>`;
    root.addEventListener("click", (event) => {
      if (event.target === root || event.target.closest("[data-viewer-close]")) this.close();
    });
    document.body.appendChild(root);
    return root;
  }
}

new ChatFileViewer().attach(document.getElementById("messages"));
