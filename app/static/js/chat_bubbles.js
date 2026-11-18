/* Message bubbles in #messages: creating them (with sender label, avatar and time), finding the one tracking a message
id, deleting a channel message, and short notes under a bubble. */
class ChatBubbles {
  // The trash-can icon, as on the sidebar's "delete chat" button (chat_sidebar.js).
  static TRASH_ICON =
    '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6h16Z"/></svg>';

  constructor(messagesEl) {
    this.messagesEl = messagesEl;
  }

  /*
   * An empty bubble and its wrapper. `senderLabel` (channels only, where several members post) adds a "who sent this"
   * row; `avatarUrl`/`initials` show on every "user" message; `senderId` (channels only) makes the avatar open the
   * profile modal.
   */
  create(role, senderLabel, avatarUrl, initials, senderId) {
    const wrapper = document.createElement("div");
    wrapper.className = "flex flex-col " + (role === "user" ? "items-end" : "items-start");
    if (senderLabel) {
      // Its own row, so attachDeleteButton can add a control beside the label; it also marks a channel message.
      const labelRow = document.createElement("div");
      labelRow.className = "message-label-row mb-1 flex items-center gap-1.5 px-1";
      const label = document.createElement("span");
      label.className = "text-xs font-medium text-slate-500";
      label.textContent = senderLabel;
      labelRow.appendChild(label);
      wrapper.appendChild(labelRow);
    }
    const bubble = document.createElement("div");
    bubble.className =
      "markdown-body max-w-[min(75ch,100%)] rounded-2xl px-4 py-2.5 text-sm leading-relaxed " +
      (role === "user" ? "bg-brand-600 text-white rounded-br-sm" : "bg-slate-800 text-slate-100 rounded-bl-sm");
    if (role === "user") {
      // Bubble and avatar side by side, avatar last so it sits on the text's side.
      const row = document.createElement("div");
      row.className = "flex max-w-full items-end justify-end gap-2";
      const avatar = document.createElement("div");
      avatar.className = "message-avatar h-6 w-6 shrink-0 rounded-full overflow-hidden text-[10px] leading-none";
      renderAvatar(avatar, avatarUrl, initials);
      if (senderId) {
        avatar.classList.add("cursor-pointer", "hover:opacity-80", "transition-opacity");
        avatar.addEventListener("click", () => userProfileModal.open(senderId));
      }
      row.append(bubble, avatar);
      wrapper.appendChild(row);
    } else {
      wrapper.appendChild(bubble);
    }
    // "Now", right for a just-sent bubble; setTime overwrites it for stored messages.
    const time = document.createElement("span");
    time.className = "message-time mt-0.5 px-1 text-[10px] text-slate-500";
    time.textContent = formatShortDateTime();
    wrapper.appendChild(time);
    return { wrapper, bubble };
  }

  /*
   * Adds a message's bubble at the end of #messages, filled. `options`: sources, senderLabel, messageId, status,
   * message (the MessageOut, for attachments, time, stats and sharing), avatarUrl, initials, senderId, errorText and
   * askedSkill (a reply: the skill its message asked for).
   */
  add(role, content, options = {}) {
    const { sources, senderLabel, messageId, status, message, avatarUrl, initials, senderId, errorText } = options;
    const sharedFrom = message && message.shared_from;
    const { wrapper, bubble } = this.create(
      ChannelShare.visualRole(role, sharedFrom), senderLabel, avatarUrl, initials, senderId
    );
    if (messageId) {
      wrapper.dataset.messageId = messageId;
      this.attachDeleteButton(wrapper, messageId);
    }
    ChatBubbles.setTime(wrapper, ChatBubbles.messageTime(message));
    ReplyStatsLine.show(wrapper, message && message.stats);
    // A finished private message can be shared to a channel; one shared in says so (chat_share.js).
    if (messageId && (!status || status === "complete")) ChannelShare.decorate(wrapper, messageId, role);
    ChannelShare.remark(wrapper, sharedFrom, message && message.sender_display_name);
    bubble._toolEvents = message && message.tool_events;
    bubble._askedSkill = options.askedSkill || null;
    // A user's /use_skill "<name>" shows as a badge, not as text (chat_skill_chip.js).
    const asked = role === "user" && typeof SkillChip !== "undefined" ? SkillChip.split(content) : null;
    ReplyBody.render(bubble, asked ? asked.text : content, status, sources, errorText);
    if (asked?.skill) bubble.prepend(SkillChip.badge(asked.skill));
    ReplyBody.renderAttachments(bubble, message);
    this.messagesEl.appendChild(wrapper);
    chatScroll.follow();
    return { wrapper, bubble };
  }

  /* The bubble already tracking `messageId`, or a new one, so poll and live paths update one node. `created`: the
  message is new to this tab. */
  findOrCreate(messageId, role, senderLabel, avatarUrl, initials, senderId) {
    const existing = this.byId(messageId);
    if (existing) return { bubble: existing.querySelector(".markdown-body"), created: false };
    chatPage.showEmptyState(false);
    const { wrapper, bubble } = this.create(role, senderLabel, avatarUrl, initials, senderId);
    wrapper.dataset.messageId = messageId;
    this.attachDeleteButton(wrapper, messageId);
    this.messagesEl.appendChild(wrapper);
    return { bubble, created: true };
  }

  byId(messageId) {
    return this.messagesEl.querySelector(`[data-message-id="${messageId}"]`);
  }

  /* A message's display time: when a reply finished, else when it was created. */
  static messageTime(message) {
    return message && (message.completed_at || message.created_at);
  }

  static setTime(wrapper, createdAt) {
    const time = wrapper && wrapper.querySelector(".message-time");
    if (time && createdAt) time.textContent = formatShortDateTime(createdAt);
  }

  /* A delete control beside a channel message's label, for viewers who can manage the channel. Safe to call again:
  live bubbles get their id later and rerun it. */
  attachDeleteButton(wrapper, messageId) {
    if (!chatPage.canManageActive) return;
    const labelRow = wrapper.querySelector(".message-label-row");
    if (!labelRow || labelRow.querySelector(".delete-message-btn")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "delete-message-btn ms-auto shrink-0 text-slate-600 hover:text-red-400 transition-colors";
    btn.title = "Delete this message";
    btn.innerHTML = ChatBubbles.TRASH_ICON;
    btn.addEventListener("click", () => this.deleteChannelMessage(messageId, wrapper));
    labelRow.appendChild(btn);
  }

  /* Deletes a channel message for good (admins/managers; enforced in routers/conversations.py). Other members see it
  go through their poll or live watch (chat_live_updates.js). */
  async deleteChannelMessage(messageId, wrapper) {
    if (!confirm("Delete this message? This can't be undone.")) return;
    let deletedIds;
    try {
      ({ deleted_message_ids: deletedIds } = await api(
        `/api/conversations/${chatPage.activeConversationId}/messages/${messageId}`,
        { method: "DELETE" }
      ));
    } catch (err) {
      alert(err.message || "Failed to delete message.");
      return;
    }
    // Deleting a question whose reply is generating removes the reply too; the response lists both. A reply still
    // reading a long prompt may have no id yet: then it is the waiting bubble right after the message.
    const nextBubble = wrapper.nextElementSibling;
    for (const id of deletedIds) {
      let el = id === messageId ? wrapper : this.byId(id);
      if (!el && nextBubble && !nextBubble.dataset.messageId && nextBubble.querySelector(".typing-dot")) el = nextBubble;
      if (el) el.remove();
      // Added, not removed: a poll in flight may still report it as streaming, and must not bring the bubble back.
      chatPage.liveMessageIds.add(id);
    }
    if (deletedIds.length > 1) chatPage.setChannelReplyInFlight(false); // the reply was stopped: ask again
    if (this.messagesEl.children.length === 0) chatPage.showEmptyState(true);
  }

  /* A short warning under a message, above its time; only in the sender's tab, not saved. */
  static showNotice(wrapper, text) {
    const notice = document.createElement("p");
    notice.className = "message-notice mt-1 max-w-[min(75ch,100%)] px-1 text-xs text-warning-400";
    notice.textContent = text;
    // Above the time's row: the share button (chat_share.js) may have moved the time into a footer.
    const time = wrapper.querySelector(".message-time");
    const anchor = time && (time.closest(".message-footer") || time);
    if (anchor && anchor.parentNode === wrapper) wrapper.insertBefore(notice, anchor);
    else wrapper.appendChild(notice);
  }

  /* A red note under the user's message for a send that made no reply: a 409 "AI busy", or a plain channel message
  that failed. A reply that started and failed shows ReplyBody.FAILED_NOTICE instead. */
  static showSendError(userWrapper, message) {
    const notice = document.createElement("div");
    notice.className = "mt-1 px-1 text-xs text-red-400";
    notice.textContent = message;
    userWrapper.appendChild(notice);
  }
}

const chatBubbles = new ChatBubbles(document.getElementById("messages"));
