/* The header's note badges (#pinned-badges): one icon per persona/rules slot of the open chat (GET
/api/notes/slots/{id}), always both and in the same order so the row doesn't jump; an off slot stays clickable to turn
it back on. Also what a started chat may still change (Admin settings > Inference > Prompt cache). */
class PinnedBadges {
  static NOTHING_CHANGES = { skills: false, notes: false, tools: false };

  constructor() {
    this.el = document.getElementById("pinned-badges");
    this.slots = [];
    // What a started chat may still change, by what its cache layout makes cheap (GET
    // /api/prompt-cache/mid-chat-changes, read on each chat switch): skills in every layout but "Stable order",
    // persona and rules only in "Add changes as updates" and "Keep unchanged blocks".
    this.midChatChanges = { ...PinnedBadges.NOTHING_CHANGES };
  }

  notesLocked() {
    return chatPage.activeHasMessages && !this.midChatChanges.notes;
  }

  skillsLocked() {
    return chatPage.activeHasMessages && !this.midChatChanges.skills;
  }

  async loadMidChatChanges() {
    try {
      this.midChatChanges = await api("/api/prompt-cache/mid-chat-changes");
    } catch (_) {
      this.midChatChanges = { ...PinnedBadges.NOTHING_CHANGES };
    }
  }

  /* Best effort: a failed lookup shows no icons. */
  async load(conversationId) {
    let slots;
    try {
      slots = await api(`/api/notes/slots/${conversationId}`);
    } catch (_) {
      return;
    }
    // Not awaited by selectConversation: a result for a chat left meanwhile must not replace the new icons.
    if (conversationId !== chatPage.activeConversationId) return;
    this.slots = slots;
    this.render();
  }

  clear() {
    this.el.innerHTML = "";
  }

  /* The note badges, then the Skills badge (chat_skills.js). Editable only for someone who can manage the chat, and
  only while the notes (or skills) aren't locked; otherwise a badge opens its note read-only. */
  render() {
    const conversationId = chatPage.activeConversationId;
    const canManage = chatPage.canManageActive;
    this.clear();
    for (const slot of this.slots) this.el.appendChild(this.badge(conversationId, slot, canManage));
    if (typeof chatSkills !== "undefined") chatSkills.render(conversationId, canManage && !this.skillsLocked());
    if (typeof chatExport !== "undefined") chatExport.render(conversationId);
  }

  badge(conversationId, slot, canManage) {
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "rounded-full px-1.5 py-0.5 transition-colors bg-slate-800 hover:bg-slate-700"; // never faded
    const state = !slot.active ? " (off)" : slot.is_override ? " (customized)" : "";
    const readOnlyNote = !canManage
      ? " — read-only (admins/managers only)"
      : this.notesLocked() ? " — locked: can only change before the first message" : "";
    badge.title = `${SlotEditor.label(slot.pin_type)}${state}: ${slot.title || ""}${readOnlyNote}`;
    const icon = document.createElement("span");
    icon.className = "inline-block";
    icon.textContent = SlotEditor.ICONS[slot.pin_type] || "📌";
    if (SlotEditor.TILT[slot.pin_type]) icon.style.transform = `rotate(${SlotEditor.TILT[slot.pin_type]}deg)`;
    badge.appendChild(icon);
    // Rights are read at click time: they change with each chat switch.
    badge.addEventListener("click", () => {
      if (chatPage.canManageActive && !this.notesLocked()) return slotEditor.open(conversationId, slot);
      const reason = !chatPage.canManageActive
        ? "Read-only: only admins and this channel's managers can change it."
        : "Locked: notes can only change before the first message.";
      slotEditor.open(conversationId, slot, reason);
    });
    return badge;
  }
}

const pinnedBadges = new PinnedBadges();
