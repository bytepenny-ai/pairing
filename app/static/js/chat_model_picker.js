/* The header's model badge (#model-badge) and the picker it opens (#model-picker), to switch the open chat to another
installed model. Past messages keep the model that wrote them. */
class ModelPicker {
  constructor() {
    this.badge = document.getElementById("model-badge");
    this.el = document.getElementById("model-picker");
    this.listEl = document.getElementById("model-picker-list");
    this.statusEl = document.getElementById("model-picker-status");
    this.warningEl = document.getElementById("model-picker-warning");
    this.confirmEl = document.getElementById("model-picker-confirm");
    this.pending = null; // the model awaiting confirmation
    document.getElementById("model-picker-confirm-btn").addEventListener("click", () => {
      if (this.pending) this.switchTo(this.pending);
    });
    document.getElementById("model-picker-cancel-btn").addEventListener("click", () => {
      this.confirmEl.classList.add("hidden");
      this.pending = null;
    });
    this.badge.addEventListener("click", () => {
      if (this.el.classList.contains("hidden")) this.open();
      else this.close();
    });
  }

  current() {
    return this.badge.textContent;
  }

  /* Shows the chat's model on the badge; null hides it (no chat open). */
  show(model) {
    this.badge.textContent = model || "";
    this.badge.classList.toggle("hidden", model === null);
  }

  /* "Click to switch" for whoever can manage the chat, plain text for other channel members. Only a look: the
  server enforces it. */
  setManageable(manageable) {
    this.badge.classList.toggle("cursor-default", !manageable);
    this.badge.classList.toggle("opacity-60", !manageable);
    this.badge.title = manageable ? "Switch model for this chat" : "Only admins and this channel's managers can change its model";
  }

  close() {
    this.el.classList.add("hidden");
    this.confirmEl.classList.add("hidden");
    this.pending = null;
  }

  /* Lists the installed models; only to change an existing chat's model (no install here). */
  async open() {
    if (!chatPage.activeConversationId || !chatPage.canManageActive) return;
    chatPage.closeHeaderPopups("model");
    this.listEl.innerHTML = "";
    this.statusEl.textContent = "Loading…";
    this.confirmEl.classList.add("hidden");
    // Allowed mid-chat (unlike notes), but the new model re-reads everything: say so.
    this.warningEl.classList.toggle("hidden", !chatPage.activeHasMessages);
    this.el.classList.remove("hidden");
    let models;
    try {
      ({ models } = await api("/api/settings/installed-models"));
    } catch (err) {
      this.statusEl.textContent = err.message;
      return;
    }
    this.statusEl.textContent = models.length === 0 ? "No models installed." : "";
    for (const model of models) this.listEl.appendChild(this.option(model));
  }

  option(model) {
    const btn = document.createElement("button");
    btn.type = "button";
    // The full name, wrapped (break-all: a GGUF file name has no natural wrap point), so similar models can be told
    // apart; the title is a hover fallback.
    btn.className =
      "w-full break-all rounded-md px-2 py-1.5 text-start font-mono text-xs leading-snug transition-colors " +
      (model === this.current() ? "bg-slate-800 text-slate-100" : "text-slate-300 hover:bg-slate-800");
    btn.textContent = model;
    btn.title = model;
    btn.addEventListener("click", () => this.askToSwitch(model));
    return btn;
  }

  /* A chat with messages asks first (the new model re-reads the whole chat); a new chat switches at once. */
  askToSwitch(model) {
    if (!chatPage.activeHasMessages || model === this.current()) {
      this.switchTo(model);
      return;
    }
    this.pending = model;
    document.getElementById("model-picker-confirm-model").textContent = model;
    this.confirmEl.classList.remove("hidden");
  }

  async switchTo(model) {
    if (model === this.current()) {
      this.close();
      return;
    }
    this.statusEl.textContent = "Switching…";
    try {
      const conversation = await api(`/api/conversations/${chatPage.activeConversationId}`, {
        method: "PATCH",
        body: JSON.stringify({ model }),
      });
      this.badge.textContent = conversation.model || "";
      thinkingChip.sync(chatPage.activeConversationId, conversation, chatPage.canManageActive);
      this.close();
    } catch (err) {
      this.statusEl.textContent = err.message;
    }
  }
}

const modelPicker = new ModelPicker();
