/* The panel to view or change one of the chat's persona/rules notes (#slot-editor), opened from its badge
(chat_pinned_badges.js): save it for this chat or for all, go back to the default, or turn it off. */
class SlotEditor {
  // The same icons as the Notes page pin chips (notes.js); these static files share no module system.
  static ICONS = { persona: "🧬", rules: "📏" };
  static TILT = { persona: -15 }; // degrees to turn an icon (negative: to the left)
  static LABELS = { persona: "Persona", rules: "Rules" };

  constructor() {
    this.el = document.getElementById("slot-editor");
    this.titleEl = document.getElementById("slot-editor-title");
    this.contentEl = document.getElementById("slot-editor-content");
    this.onlyThisChatEl = document.getElementById("slot-editor-only-this-chat");
    this.statusEl = document.getElementById("slot-editor-status");
    this.lockedEl = document.getElementById("slot-editor-locked");
    this.useDefaultBtn = document.getElementById("slot-editor-use-default");
    this.turnOffBtn = document.getElementById("slot-editor-turn-off");
    this.saveBtn = document.getElementById("slot-editor-save");
    this.cancelBtn = document.getElementById("slot-editor-cancel");
    this.editing = null; // {conversationId, pinType} while open
    this.cancelBtn.addEventListener("click", () => this.close());
    this.saveBtn.addEventListener("click", () =>
      this.apply("", {
        method: "PUT",
        body: JSON.stringify({ content: this.contentEl.value, only_this_chat: this.onlyThisChatEl.checked }),
      })
    );
    // "Use default" and "Enable" are one action: an override goes back to the default, an off slot is turned on.
    this.useDefaultBtn.addEventListener("click", () => this.apply("/use-default", { method: "POST" }));
    this.turnOffBtn.addEventListener("click", () => this.apply("", { method: "DELETE" }));
  }

  static label(pinType) {
    return SlotEditor.LABELS[pinType] || pinType;
  }

  close() {
    this.editing = null;
    this.el.classList.add("hidden");
  }

  /* `lockedReason`: shows the note read-only, with why it can't change now. */
  open(conversationId, slot, lockedReason = "") {
    chatPage.closeHeaderPopups("slot");
    this.editing = { conversationId, pinType: slot.pin_type };
    const state = !slot.active ? " (off)" : slot.is_override ? " (customized)" : " (default)";
    this.titleEl.textContent = `${SlotEditor.label(slot.pin_type)} for this chat${state}`;
    this.contentEl.value = slot.content || "";
    this.contentEl.dir = detectTextDirection(this.contentEl.value);
    // Checked for a per-chat override, unchecked on the shared default.
    this.onlyThisChatEl.checked = slot.is_override;
    // Hidden when it is already the active default.
    this.useDefaultBtn.classList.toggle("hidden", slot.active && !slot.is_override);
    this.useDefaultBtn.textContent = slot.active ? "Use default" : "Enable";
    this.turnOffBtn.classList.toggle("hidden", !slot.active);
    this.statusEl.textContent = "";
    const locked = Boolean(lockedReason);
    this.lockedEl.textContent = lockedReason;
    this.lockedEl.classList.toggle("hidden", !locked);
    this.contentEl.readOnly = locked;
    // Off and locked: the chat doesn't use it and it can't be turned on, so only the title and the reason show.
    this.contentEl.classList.toggle("hidden", locked && !slot.active);
    document.getElementById("slot-editor-only-this-chat-row").classList.toggle("hidden", locked);
    this.saveBtn.classList.toggle("hidden", locked);
    if (locked) [this.useDefaultBtn, this.turnOffBtn].forEach((b) => b.classList.add("hidden"));
    this.cancelBtn.textContent = locked ? "Close" : "Cancel";
    this.el.classList.remove("hidden");
    if (!locked) this.contentEl.focus();
  }

  /* Sends one change for the open slot (/api/notes/slots/{id}/{type}`suffix`), then redraws the badges. */
  async apply(suffix, request) {
    if (!this.editing) return;
    const { conversationId, pinType } = this.editing;
    if (request.method === "PUT") this.statusEl.textContent = "Saving…";
    try {
      await api(`/api/notes/slots/${conversationId}/${pinType}${suffix}`, request);
      this.close();
      pinnedBadges.load(conversationId);
    } catch (err) {
      this.statusEl.textContent = err.message;
    }
  }
}

const slotEditor = new SlotEditor();
