/* The chat page's sidebar: the personal chats and channels lists, chat titles (also a "smart" title generated after the
first reply), and the one-time "New: UI themes" notice. */
class ChatSidebar {
  // A title still generating when the first reply ended ("smart" mode, title_service.py) is checked this many times,
  // this far apart; a slow model leaves "New chat" until reload rather than a timer polling forever.
  static TITLE_POLL_ATTEMPTS = 6;
  static TITLE_POLL_INTERVAL_MS = 5000;
  static WHATS_NEW_THEMES_KEY = "pairing:whatsNewThemesDismissed";

  constructor() {
    this.conversationListEl = document.getElementById("conversation-list");
    this.channelListEl = document.getElementById("channel-list");
    document.getElementById("new-chat-btn").addEventListener("click", () => chatPage.createNewConversation());
    this.initWhatsNewThemes();
  }

  /* In localStorage rather than a per-user server flag: a one-off notice isn't worth a round trip. */
  initWhatsNewThemes() {
    const notice = document.getElementById("whats-new-themes");
    let dismissed = false;
    try {
      dismissed = localStorage.getItem(ChatSidebar.WHATS_NEW_THEMES_KEY) === "1";
    } catch (_) {
      /* storage disabled: always show it */
    }
    notice.classList.toggle("hidden", dismissed);
    document.getElementById("whats-new-themes-dismiss").addEventListener("click", () => {
      notice.classList.add("hidden");
      try {
        localStorage.setItem(ChatSidebar.WHATS_NEW_THEMES_KEY, "1");
      } catch (_) {
        /* storage disabled: reappears next load */
      }
    });
    // The same tab handoff as account_panel.js's "Go to Settings" link: a plain href would land on the Model tab.
    document.getElementById("whats-new-themes-settings-link").addEventListener("click", () => {
      try {
        sessionStorage.setItem("pairingSettingsActiveTab", "account");
      } catch (_) {
        /* storage blocked: settings.js opens its default tab */
      }
    });
  }

  /* A "No chats"/"No channels" row, so an empty list doesn't look like loading or broken. */
  placeholder(container, text) {
    const placeholder = document.createElement("p");
    placeholder.className = "px-3 py-2 text-xs text-slate-500";
    placeholder.textContent = text;
    container.appendChild(placeholder);
  }

  async loadConversations() {
    const conversations = await api("/api/conversations");
    this.conversationListEl.innerHTML = "";
    for (const conversation of conversations) this.conversationListEl.appendChild(this.conversationItem(conversation));
    if (conversations.length === 0) this.placeholder(this.conversationListEl, "No chats");
    return conversations;
  }

  /* Loads the channels into the list and into chatPage.channels (by conversation id). */
  async loadChannels() {
    const channels = await api("/api/channels");
    chatPage.channels = {};
    this.channelListEl.innerHTML = "";
    for (const channel of channels) {
      chatPage.channels[channel.conversation_id] = channel;
      this.channelListEl.appendChild(this.channelItem(channel));
    }
    if (channels.length === 0) this.placeholder(this.channelListEl, "No channels");
  }

  row(id) {
    const item = document.createElement("div");
    item.dataset.id = id;
    item.className =
      "group flex items-center rounded-lg pr-1 text-sm transition-colors " +
      (id === chatPage.activeConversationId ? "bg-slate-800 text-slate-100" : "text-slate-300 hover:bg-slate-800/60");
    return item;
  }

  conversationItem(conversation) {
    const item = this.row(conversation.id);
    const titleBtn = document.createElement("button");
    titleBtn.type = "button";
    // text-left, not text-start: the row stays aligned with the sidebar; only the text follows the title's direction.
    titleBtn.className = "flex-1 min-w-0 truncate px-3 py-2 text-left";
    const titleText = conversation.title || "New chat";
    titleBtn.dir = detectTextDirection(titleText);
    titleBtn.textContent = titleText;
    titleBtn.addEventListener("click", () => chatPage.selectConversation(conversation.id));

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.title = "Delete chat";
    deleteBtn.className =
      "shrink-0 rounded p-1.5 text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-700 hover:text-red-400 transition-opacity";
    deleteBtn.innerHTML = ChatBubbles.TRASH_ICON;
    deleteBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      chatPage.deleteConversation(conversation.id);
    });
    item.append(titleBtn, deleteBtn);
    return item;
  }

  /* No delete button: channels are managed by admins in Admin settings > Channels. */
  channelItem(channel) {
    const item = this.row(channel.conversation_id);
    const titleBtn = document.createElement("button");
    titleBtn.type = "button";
    titleBtn.className = "flex-1 min-w-0 flex items-center gap-1.5 truncate px-3 py-2 text-left";
    titleBtn.innerHTML = `<span class="text-slate-500">#</span><span class="min-w-0 truncate"></span>`;
    const label = titleBtn.querySelector("span:last-child");
    label.dir = detectTextDirection(channel.name);
    label.textContent = channel.name;
    titleBtn.addEventListener("click", () => chatPage.selectConversation(channel.conversation_id));
    item.appendChild(titleBtn);
    return item;
  }

  /* A new chat goes first in the list, replacing the "No chats" row (the only <p> there). */
  addConversation(conversation) {
    this.conversationListEl.querySelector("p")?.remove();
    this.conversationListEl.prepend(this.conversationItem(conversation));
  }

  /* Removes a chat's row; returns the id of the first remaining chat, or null. */
  removeConversation(id) {
    this.conversationListEl.querySelector(`[data-id="${id}"]`)?.remove();
    const next = this.conversationListEl.querySelector("[data-id]");
    if (!next) this.placeholder(this.conversationListEl, "No chats");
    return next ? next.dataset.id : null;
  }

  highlightActive() {
    for (const item of [...this.conversationListEl.children, ...this.channelListEl.children]) {
      item.classList.toggle("bg-slate-800", item.dataset.id === chatPage.activeConversationId);
      item.classList.toggle("text-slate-100", item.dataset.id === chatPage.activeConversationId);
    }
  }

  /* Shows a chat's new title in its row, and in the header if it is open. */
  showTitle(conversationId, title) {
    if (conversationId === chatPage.activeConversationId) chatPage.showTitle(title);
    const item = this.conversationListEl.querySelector(`[data-id="${conversationId}"] button`);
    if (item) {
      item.textContent = title;
      item.dir = detectTextDirection(title);
    }
  }

  async pollForTitle(conversationId, attempt = 1) {
    let conversation;
    try {
      conversation = await api(`/api/conversations/${conversationId}`);
    } catch (_) {
      return;
    }
    if (conversation.title && conversation.title !== "New chat") {
      this.showTitle(conversationId, conversation.title);
      return;
    }
    if (attempt < ChatSidebar.TITLE_POLL_ATTEMPTS) {
      setTimeout(() => this.pollForTitle(conversationId, attempt + 1), ChatSidebar.TITLE_POLL_INTERVAL_MS);
    }
  }
}

const chatSidebar = new ChatSidebar();
