/* Shows replies this tab didn't send, as they happen: other channel members' messages, or a personal chat's reply that
kept generating after its connection dropped. Two ways, one at a time: a live watch (an EventSource on routers/chat.py's
/subscribe; a channel in "real" delivery mode, or one personal reply) or a poll every few seconds (a channel in "cheap"
mode). Either way, a full reload of the messages (reconcile) is the backstop for missed events. */
class ChatLiveUpdates {
  // How often "cheap" mode checks for new or changed messages; no attempt cap, as a channel chat is open-ended.
  static POLL_INTERVAL_MS = 3000;

  constructor() {
    this.source = null; // the open live watch
    this.oneShot = false; // the watch closes once its one reply settles (a personal chat's reconnect)
    this.pollTimeoutId = null;
    this.pollSince = null; // the last poll's server_time: the next one fetches only what's new
    // Text so far per message id of a reply watched live. The source of truth, not the DOM, since a reconcile can
    // replace the node mid-reply.
    this.liveContent = new Map();
  }

  /* Reloads and redraws the whole conversation: after a watched reply ends, or when a message has no bubble yet. The
  broadcast hub can drop events under load, and carries no user messages. */
  async reconcile(conversationId) {
    if (conversationId !== chatPage.activeConversationId) return;
    let messages;
    try {
      messages = await api(`/api/conversations/${conversationId}/messages`);
    } catch (_) {
      return;
    }
    if (conversationId !== chatPage.activeConversationId) return;
    chatPage.renderMessageList(messages, chatPage.channels[conversationId] || null);
  }

  /* Stops the watch or poll of the conversation being left. */
  stop() {
    if (this.source) {
      this.source.close();
      this.source = null;
    }
    this.oneShot = false;
    if (this.pollTimeoutId) {
      clearTimeout(this.pollTimeoutId);
      this.pollTimeoutId = null;
    }
    this.pollSince = null;
    this.liveContent.clear();
  }

  /* A read-only EventSource for this conversation's reply events (GET, auto-reconnecting). `oneShot`: watch one
  personal reply until it settles; otherwise a channel's whole activity while it is open. */
  watch(conversationId, oneShot) {
    const source = new EventSource(`/api/chat/${conversationId}/subscribe`);
    this.source = source;
    this.oneShot = !!oneShot;
    source.onmessage = (event) => this.handle(conversationId, JSON.parse(event.data));
  }

  handle(conversationId, payload) {
    if (conversationId !== chatPage.activeConversationId) return;
    // This tab's own send is rendering its reply; skip events for the whole send (see ChatPage.ownSendInFlight).
    if (chatPage.ownSendInFlight) return;
    const messageId = payload.message_id;
    if (!messageId || chatPage.liveMessageIds.has(messageId)) return;
    const bubbleOf = () => chatBubbles.findOrCreate(messageId, "assistant", "AI");

    if (payload.sync) {
      this.liveContent.set(messageId, payload.content || "");
      if (payload.status !== "streaming") return;
      chatPage.setChannelReplyInFlight(true);
      const { bubble, created } = bubbleOf();
      bubble._toolEvents = payload.tool_events;
      bubble._reasoning = payload.reasoning;
      this.applyProgress(bubble, payload);
      ReplyBody.render(bubble, this.liveContent.get(messageId), payload.status);
      chatScroll.follow();
      if (created) this.reconcile(conversationId);
      return;
    }
    if (payload.tool) ToolBlocks.add(bubbleOf().bubble, payload.tool);
    if (payload.reasoning) {
      const { bubble } = bubbleOf();
      ReasoningSteps.set(bubble, payload.reasoning);
      ReplyBody.render(bubble, this.liveContent.get(messageId) || "", "streaming");
    }
    if (payload.read_progress != null || payload.compacting) {
      const { bubble } = bubbleOf();
      this.applyProgress(bubble, payload);
      ReplyBody.render(bubble, this.liveContent.get(messageId) || "", "streaming");
    }
    if (payload.chunk) {
      chatPage.setChannelReplyInFlight(true);
      const text = (this.liveContent.get(messageId) || "") + payload.chunk;
      this.liveContent.set(messageId, text);
      const { bubble, created } = bubbleOf();
      ReplyBody.render(bubble, text, "streaming");
      chatScroll.follow();
      // New to this tab: one reconcile fetches its question and anything missed.
      if (created) this.reconcile(conversationId);
    }
    if (payload.deleted) {
      this.settle(conversationId, messageId);
      chatBubbles.byId(messageId)?.remove();
      return;
    }
    if (payload.done || payload.error) this.settle(conversationId, messageId);
  }

  /* A watched reply ended (done, failed or deleted): the reconcile is the authority on what remains, including a
  deleted reply's question. A one-shot watch closes; a channel's stays open. */
  settle(conversationId, messageId) {
    chatPage.setChannelReplyInFlight(false);
    this.liveContent.delete(messageId);
    this.reconcile(conversationId);
    if (this.oneShot) this.stop();
  }

  applyProgress(bubble, state) {
    if (state.read_progress != null) ReadProgress.set(bubble, state.read_progress);
    if (state.compacting) ReadProgress.compacting(bubble);
  }

  startPolling(conversationId) {
    this.pollSince = null;
    this.schedulePoll(conversationId);
  }

  schedulePoll(conversationId) {
    this.pollTimeoutId = setTimeout(() => this.poll(conversationId), ChatLiveUpdates.POLL_INTERVAL_MS);
  }

  async poll(conversationId) {
    if (conversationId !== chatPage.activeConversationId) return;
    let result;
    try {
      const query = this.pollSince ? `?since=${encodeURIComponent(this.pollSince)}` : "";
      result = await api(`/api/conversations/${conversationId}/messages/latest${query}`);
    } catch (_) {
      this.schedulePoll(conversationId);
      return;
    }
    if (conversationId !== chatPage.activeConversationId) return;
    // Skipped while this tab's own send is in flight: its reply is in the database before the stream tags it.
    // pollSince stays, so this window is read again after the send.
    if (chatPage.ownSendInFlight) {
      this.schedulePoll(conversationId);
      return;
    }
    this.pollSince = result.server_time;
    const channelInfo = chatPage.channels[conversationId] || null;
    for (const message of result.messages) {
      if (message.role === "assistant") chatPage.channelReplyInFlight = message.status === "streaming";
      if (message.status === "deleted") {
        // Before the live-id skip: a message this tab sent can still be deleted by someone else.
        chatBubbles.byId(message.id)?.remove();
        chatPage.liveMessageIds.add(message.id); // never recreate it, however stale a later response is
        continue;
      }
      if (chatPage.liveMessageIds.has(message.id)) continue;
      this.showPolled(message, channelInfo);
    }
    this.showWaitingReply(result.live);
    chatPage.updateAskAiButton();
    if (chatPage.messagesEl.children.length === 0) chatPage.showEmptyState(true);
    this.schedulePoll(conversationId);
  }

  showPolled(message, channelInfo) {
    const senderLabel = channelInfo ? (message.role === "assistant" ? "AI" : message.sender_display_name) : null;
    const senderId = channelInfo && message.role === "user" ? message.sender_id : null;
    const { bubble } = chatBubbles.findOrCreate(
      message.id,
      ChannelShare.visualRole(message.role, message.shared_from),
      senderLabel,
      message.sender_avatar_url,
      message.sender_initials,
      senderId
    );
    const wrapper = bubble.closest("[data-message-id]");
    ChatBubbles.setTime(wrapper, ChatBubbles.messageTime(message));
    ReplyStatsLine.show(wrapper, message.stats);
    ChannelShare.remark(wrapper, message.shared_from, message.sender_display_name);
    bubble._toolEvents = message.tool_events;
    ReplyBody.render(bubble, message.content, message.status, message.sources, message.error_message);
    ReplyBody.renderAttachments(bubble, message);
    chatScroll.follow();
  }

  /* The polled reply still waiting for its first words (MessagesLatestResponse.live) keeps its label (reasoning,
  "Compacting cache…", read progress), also after leaving the channel and coming back. */
  showWaitingReply(live) {
    if (!live || chatPage.liveMessageIds.has(live.message_id)) return;
    const bubble = chatBubbles.byId(live.message_id)?.querySelector(".markdown-body");
    if (!bubble) return;
    bubble._reasoning = live.reasoning;
    this.applyProgress(bubble, live);
    ReplyBody.render(bubble, "", "streaming");
  }
}

const chatLive = new ChatLiveUpdates();
