/* Chat header "Reasoning" chip (conversation.params.think: the engines' thinking switch; hidden while Admin settings > System > Reasoning is off): click goes off -> on -> auto
(the model's choice: think "auto", services/think_mode.py) -> off. Off by default; a chat saved with no value counts as off. Saved for this chat
like the Tools switch (chat_tools.js). Shown only when the chat's model can think (GET
/api/settings/model-capabilities reports "thinking"). When the model's switch sits early in the prompt
("thinking_rereads", e.g. Gemma 4), a chat with messages is re-read once after a change, so it asks first, like the
model picker. Uses api from app.js and activeHasMessages from chat.js. */
class ThinkingChip {
  static STATES = {
    off: { label: "Reasoning: off", title: "Answers right away, never reasons first. Click: always reason" },
    on: { label: "Reasoning: on", title: "Reasons before answering (slower, better on hard questions). Click: let the model decide" },
    auto: { label: "Reasoning: auto", title: "The model decides when to reason (most answer right away). Click: off" },
  };
  static NEXT = { off: true, on: "auto", auto: false };

  /* "on", "off" or "auto" from the chat's saved value (anything else counts as off). */
  static stateOf(think) {
    return think === true ? "on" : think === "auto" ? "auto" : "off";
  }

  constructor(button) {
    this.button = button;
    this.conversationId = null;
    this.params = null;
    this.capabilities = [];
    this.confirmBox = this.buildConfirm();
    // Beside the other header popups (chat.html #model-picker), so it opens at the same height.
    document.getElementById("model-picker").parentElement.appendChild(this.confirmBox);
    button.addEventListener("click", () => this.click());
  }

  buildConfirm() {
    const box = document.createElement("div");
    box.id = "thinking-confirm";
    box.className =
      "hidden absolute right-4 top-14 z-20 w-80 max-w-[calc(100%-2rem)] space-y-2 rounded-lg border border-slate-700 bg-slate-900 p-3 text-xs shadow-lg";
    box.innerHTML = `
      <p class="rounded-lg border border-warning-500/50 bg-slate-900 px-3 py-2 leading-snug text-warning-400">
        This chat already has messages. With this model, changing Reasoning makes it read the whole conversation again
        before its next reply (once). On a long chat this can take minutes, depending on your system.
      </p>
      <div class="flex gap-2">
        <button type="button" data-change class="rounded-md bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-500">Change</button>
        <button type="button" data-cancel class="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800">Cancel</button>
      </div>`;
    box.querySelector("[data-change]").addEventListener("click", () => {
      box.classList.add("hidden");
      this.next();
    });
    box.querySelector("[data-cancel]").addEventListener("click", () => box.classList.add("hidden"));
    return box;
  }

  click() {
    if (this.capabilities.includes("thinking_rereads") && activeHasMessages) {
      const opening = this.confirmBox.classList.contains("hidden");
      if (opening) closeHeaderPopups("thinking");
      this.confirmBox.classList.toggle("hidden", !opening);
      return;
    }
    this.next();
  }

  closeConfirm() {
    this.confirmBox.classList.add("hidden");
  }

  /* Called when a chat opens or its model changes. */
  async sync(conversationId, conversation, canManage) {
    this.conversationId = conversationId;
    this.params = conversation.params || {};
    this.button.disabled = !canManage;
    this.capabilities = [];
    this.confirmBox.classList.add("hidden");
    this.render();
    this.button.classList.add("hidden");
    let capabilities = null;
    let allowed = true;
    try {
      // Admin settings > System > Reasoning can block it for everyone: then no chip at all.
      [{ capabilities }, { enabled: allowed }] = await Promise.all([
        api(`/api/settings/model-capabilities?model=${encodeURIComponent(conversation.model || "")}`),
        api("/api/settings/reasoning"),
      ]);
    } catch (_err) {
      return;
    }
    if (this.conversationId === conversationId) {
      this.capabilities = capabilities || [];
      this.button.classList.toggle("hidden", !allowed || !this.capabilities.includes("thinking"));
    }
  }

  hide() {
    this.conversationId = null;
    this.button.classList.add("hidden");
    this.confirmBox.classList.add("hidden");
  }

  get on() {
    return this.params?.think === true && !this.button.classList.contains("hidden");
  }

  render() {
    const key = ThinkingChip.stateOf(this.params?.think);
    const state = ThinkingChip.STATES[key];
    this.button.textContent = state.label;
    this.button.title = this.button.disabled ? "Only a channel manager can change this" : state.title;
    this.button.classList.toggle("text-brand-500", key !== "off");
  }

  async next() {
    const params = { ...this.params, think: ThinkingChip.NEXT[ThinkingChip.stateOf(this.params?.think)] };
    const id = this.conversationId;
    try {
      const conversation = await api(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ params }) });
      if (this.conversationId === id) {
        this.params = conversation.params;
        this.render();
      }
    } catch (err) {
      this.button.title = err.message;
    }
  }
}

const thinkingChip = new ThinkingChip(document.getElementById("thinking-chip"));
