/* The chat page: which conversation is open and its state, switching, creating and deleting conversations, and drawing
a conversation's messages. The parts live in their own classes: chat_sidebar.js, chat_composer.js, chat_send.js,
chat_reply_stream.js, chat_live_updates.js, chat_bubbles.js, chat_reply_body.js, chat_markdown.js,
chat_pinned_badges.js, chat_slot_editor.js, chat_model_picker.js and chat_user_profile.js. */
class ChatPage {
  constructor() {
    this.messagesEl = document.getElementById("messages");
    this.emptyStateEl = document.getElementById("empty-state");
    this.titleEl = document.getElementById("conversation-title");
    this.user = ChatPage.readUser();
    this.activeConversationId = null; // the conversation on screen
    // A channel's ChannelSummary (GET /api/channels) by its conversation id: tells channels from personal chats.
    this.channels = {};
    // Whether this viewer can change the open chat's model, notes and skills: always in a personal chat, only admins
    // and the channel's managers in a channel. The server enforces it; this only hides controls that would fail.
    this.canManageActive = true;
    this.activeHasMessages = false;
    // How other members see a channel reply: "cheap" (poll) or "real" (pushed live); loaded in init.
    this.channelDeliveryMode = "cheap";
    // Message ids this tab renders from its own send; the poll and live watch skip them. Reset on each switch.
    this.liveMessageIds = new Set();
    // True during this tab's own send. A channel's live watch is already open, so it and the send's own request both
    // get the first event before either tags it, which made a second bubble (most visible on an instant failure).
    this.ownSendInFlight = false;
    // This tab's in-flight send request, aborted when the reader leaves its conversation.
    this.activeStream = null;
    // A mirror of the server's guard (conversation_service.has_active_reply): some member's reply is generating in
    // the channel, so "Ask AI" is off. Not authoritative: the server answers 409 if it drifts.
    this.channelReplyInFlight = false;
  }

  /* The signed-in user, from <body>'s data attributes (base.html), to show a just-sent message at once. */
  static readUser() {
    const data = document.body.dataset;
    const username = data.username || "";
    const fullName = [data.firstName, data.lastName].filter(Boolean).join(" ");
    const letters = [data.firstName, data.lastName].filter(Boolean).map((n) => n[0]);
    return {
      isAdmin: data.isAdmin === "true",
      id: data.userId || null,
      // As Message.sender_display_name: the name with the username in parentheses.
      displayName: fullName ? `${fullName} (${username})` : username,
      avatarUrl: data.avatarUrl || null,
      initials: (letters.length ? letters.join("") : username[0] || "?").toUpperCase(),
    };
  }

  async init() {
    showQueuedSystemMessage(); // a message a redirecting page queued (e.g. Settings after saving)
    // Always lands on the empty state, never the newest chat: opening a chat is an explicit click.
    await Promise.all([chatSidebar.loadChannels(), chatSidebar.loadConversations(), this.loadChannelDeliveryMode()]);
    this.showEmptyState(true);
  }

  /* Readable by every user (chat_settings_service.get_channel_delivery_mode); a failure keeps "cheap". */
  async loadChannelDeliveryMode() {
    try {
      ({ mode: this.channelDeliveryMode } = await api("/api/settings/channel-delivery-mode"));
    } catch (_) {
      // Keep the default.
    }
  }

  setChannelReplyInFlight(inFlight) {
    this.channelReplyInFlight = inFlight;
    this.updateAskAiButton();
  }

  updateAskAiButton() {
    chatComposer.setAskAiBusy(this.channelReplyInFlight);
  }

  showEmptyState(show) {
    this.emptyStateEl.classList.toggle("hidden", !show);
    this.messagesEl.classList.toggle("hidden", show);
  }

  showTitle(title) {
    this.titleEl.textContent = title;
    this.titleEl.dir = detectTextDirection(title);
  }

  /* Opening one header popup closes the others: `keep` names the one being opened. */
  closeHeaderPopups(keep) {
    if (keep !== "slot") slotEditor.close();
    if (keep !== "model") modelPicker.close();
    if (keep !== "skills" && typeof chatSkills !== "undefined") chatSkills.close();
    if (keep !== "export" && typeof chatExport !== "undefined") chatExport.closeMenu();
    if (keep !== "thinking" && typeof thinkingChip !== "undefined") thinkingChip.closeConfirm();
  }

  /* Scrolls #messages to the bottom, re-checking over a few frames until its height stops growing: the Tailwind
  runtime styles new elements a moment later (base.html). Capped, so a pathological case gives up. */
  scrollToBottom() {
    const el = this.messagesEl;
    let lastHeight = -1;
    let stableFrames = 0;
    const step = (frame) => {
      const height = el.scrollHeight;
      stableFrames = height === lastHeight ? stableFrames + 1 : 0;
      lastHeight = height;
      el.scrollTop = height;
      if (stableFrames < 2 && frame < 30) requestAnimationFrame(() => step(frame + 1));
    };
    step(0);
  }

  /* Ends what belongs to the conversation being left: its send request (a personal chat's reply is cancelled, a
  channel's keeps generating), its live watch or poll, and its popups. */
  leaveConversation() {
    this.activeStream?.abort();
    this.activeStream = null;
    chatLive.stop();
    this.liveMessageIds = new Set();
    slotEditor.close();
    modelPicker.close();
  }

  clearMainPane() {
    this.leaveConversation();
    this.activeConversationId = null;
    this.canManageActive = true;
    this.showTitle("");
    pinnedBadges.clear();
    if (typeof chatSkills !== "undefined") chatSkills.render(null, false);
    if (typeof chatExport !== "undefined") chatExport.render(null);
    modelPicker.show(null);
    modelPicker.setManageable(true);
    thinkingChip.hide();
    this.messagesEl.innerHTML = "";
    this.showEmptyState(true);
    chatComposer.askAiBtn.classList.add("hidden");
    this.setChannelReplyInFlight(false);
  }

  async selectConversation(id) {
    this.activeConversationId = id;
    if (typeof skillChip !== "undefined") skillChip.clear(); // a skill picked for one chat isn't another's
    chatScroll.following = true; // opening a chat starts at its latest message
    this.leaveConversation();
    chatSidebar.highlightActive();
    const channelInfo = this.channels[id] || null;
    this.canManageActive = !channelInfo || this.user.isAdmin || channelInfo.is_manager;
    modelPicker.setManageable(this.canManageActive);
    chatComposer.askAiBtn.classList.toggle("hidden", !channelInfo);

    const conversation = await api(`/api/conversations/${id}`);
    // A channel shows the channel's name (Admin settings > Channels), never conversation.title.
    this.showTitle(channelInfo ? channelInfo.name : conversation.title || "New chat");
    modelPicker.show(conversation.model || "");
    toolToggle.sync(id, conversation, this.canManageActive);
    thinkingChip.sync(id, conversation, this.canManageActive);
    this.activeHasMessages = false;
    pinnedBadges.load(id);

    const [messages] = await Promise.all([api(`/api/conversations/${id}/messages`), pinnedBadges.loadMidChatChanges()]);
    this.renderMessageList(messages, channelInfo);
    if (id === this.activeConversationId) {
      this.activeHasMessages = messages.length > 0;
      pinnedBadges.render();
    }
    this.watch(id, channelInfo, messages);
  }

  /* A channel is watched for other members' activity while open, the way channelDeliveryMode says. A personal chat
  whose last reply is still "streaming" lost its connection (reload, another tab) while the server kept generating:
  that one reply is watched until it settles. */
  watch(id, channelInfo, messages) {
    if (channelInfo) {
      if (this.channelDeliveryMode === "real") chatLive.watch(id);
      else chatLive.startPolling(id);
      return;
    }
    const last = messages[messages.length - 1];
    if (last && last.role === "assistant" && last.status === "streaming") chatLive.watch(id, true);
  }

  async createNewConversation() {
    const conversation = await api("/api/conversations", { method: "POST", body: JSON.stringify({}) });
    // Selected first: if the sidebar row fails to draw, the chat still works.
    await this.selectConversation(conversation.id);
    chatSidebar.addConversation(conversation);
  }

  /* Deletes a chat for good (confirmed first). If it was open, the first remaining chat opens, or the empty state. */
  async deleteConversation(id) {
    if (!confirm("Delete this chat? This can't be undone.")) return;
    await api(`/api/conversations/${id}`, { method: "DELETE" });
    const next = chatSidebar.removeConversation(id);
    if (id !== this.activeConversationId) return;
    if (next) await this.selectConversation(next);
    else this.clearMainPane();
  }

  /* Draws a conversation's messages from scratch: on opening it, and on each reconcile (chat_live_updates.js). */
  renderMessageList(messages, channelInfo) {
    // A redraw while the reader is further up (a channel resync) keeps their place; otherwise it ends at the bottom.
    const following = chatScroll.following;
    const readingAt = this.messagesEl.scrollTop;
    this.messagesEl.innerHTML = "";
    this.showEmptyState(messages.length === 0);
    let askedSkill = null; // the last user message's /use_skill, for the reply after it
    for (const message of messages) {
      if (message.role === "user" && typeof SkillChip !== "undefined") askedSkill = SkillChip.split(message.content).skill;
      // Sender labels and clickable avatars only in a channel, where several members post.
      const senderLabel = channelInfo ? (message.role === "assistant" ? "AI" : message.sender_display_name) : null;
      chatBubbles.add(message.role, message.content, {
        sources: message.sources,
        senderLabel,
        messageId: message.id,
        status: message.status,
        message,
        avatarUrl: message.sender_avatar_url,
        initials: message.sender_initials,
        senderId: channelInfo && message.role === "user" ? message.sender_id : null,
        errorText: message.error_message,
        askedSkill: message.role === "assistant" ? askedSkill : null,
      });
    }
    if (messages.length > 0) {
      if (following) chatScroll.jump();
      else this.messagesEl.scrollTop = readingAt;
    }
    if (channelInfo) {
      // The database's state: the most reliable point to know whether a reply is still generating.
      const last = messages[messages.length - 1];
      this.setChannelReplyInFlight(!!(last && last.role === "assistant" && last.status === "streaming"));
    }
  }
}

const chatPage = new ChatPage();
chatPage.init();
