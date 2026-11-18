/* Sends the composer's message: shows it at once, adds a waiting reply bubble when the AI is asked, streams the reply
(chat_reply_stream.js) and shows a failure where a reload would show it. */
class MessageSender {
  /* `askAi` false: a plain channel message, no AI reply (Send in a channel). True: "Ask AI", and every personal chat. */
  async send(askAi) {
    if (!chatComposer.text()) return;
    // A skill picked with /use_skill rides along as its command (chat_skill_chip.js); the badge clears with the send.
    const hasSkillChip = typeof skillChip !== "undefined";
    const content = hasSkillChip ? skillChip.withCommand(chatComposer.text()) : chatComposer.text();
    if (hasSkillChip) skillChip.clear();
    if (!chatPage.activeConversationId) await chatPage.createNewConversation();
    // Kept for the whole send: the reader may switch chats while it streams.
    const conversationId = chatPage.activeConversationId;
    const files = chatComposer.takeFiles();
    chatPage.showEmptyState(false);
    chatComposer.clearText();
    chatComposer.sendBtn.disabled = true;
    chatComposer.askAiBtn.disabled = true;

    const inChannel = !!chatPage.channels[conversationId];
    const userWrapper = this.showOwnMessage(content, files, inChannel);
    chatScroll.jump(); // the reader just wrote: show it and follow the reply
    if (askAi && files.length > 0) VectorSpace.cover(userWrapper, "files", files.length);
    if (!chatPage.activeHasMessages) {
      chatPage.activeHasMessages = true;
      pinnedBadges.render();
    }
    const { wrapper, bubble } = askAi ? this.showWaitingReply(content, inChannel) : { wrapper: null, bubble: null };

    chatPage.ownSendInFlight = true;
    try {
      await this.stream(new ReplyStream(conversationId, content, askAi, userWrapper, wrapper, bubble, files));
    } catch (err) {
      this.showFailure(err, userWrapper, wrapper, bubble, inChannel);
    } finally {
      VectorSpace.reveal(userWrapper); // however the send ended
      chatPage.ownSendInFlight = false;
      chatComposer.sendBtn.disabled = false;
      chatPage.updateAskAiButton();
      chatComposer.input.focus();
    }
  }

  /* The sender's message, before the server round trip: local file URLs serve only this first render (a later full
  redraw uses the server's). */
  showOwnMessage(content, files, inChannel) {
    const user = chatPage.user;
    const message = {
      attachments: files.map((file) => ({
        url: URL.createObjectURL(file),
        filename: file.name,
        type: file.type.startsWith("image/") ? "image" : "text",
      })),
    };
    const { wrapper } = chatBubbles.add("user", content, {
      senderLabel: inChannel ? user.displayName : null,
      message,
      avatarUrl: user.avatarUrl,
      initials: user.initials,
      senderId: inChannel ? user.id : null,
    });
    return wrapper;
  }

  showWaitingReply(content, inChannel) {
    const { wrapper, bubble } = chatBubbles.create("assistant", inChannel ? "AI" : null);
    bubble._askedSkill = typeof SkillChip !== "undefined" ? SkillChip.split(content).skill : null;
    ReplyBody.render(bubble, "", "streaming");
    chatPage.messagesEl.appendChild(wrapper);
    chatScroll.follow();
    if (inChannel) chatPage.setChannelReplyInFlight(true);
    return { wrapper, bubble };
  }

  /* Runs the stream with its request registered, so leaving the chat aborts it (a personal chat's reply is then
  cancelled on the server; a channel's keeps generating). */
  async stream(replyStream) {
    try {
      await replyStream.run((xhr) => (chatPage.activeStream = xhr));
    } finally {
      chatPage.activeStream = null;
    }
  }

  showFailure(err, userWrapper, wrapper, bubble, inChannel) {
    if (err.name === "AbortError") return; // the reader left this chat: its bubbles are gone
    if (err.status === 409) {
      // Nothing was saved: another member's reply is still active, as "Ask AI" being busy says.
      ChatBubbles.showSendError(userWrapper, err.message);
    } else if (bubble && userWrapper.dataset.messageId) {
      // The message was saved, then the reply failed: as a reload shows it, with the browser's reason (a dropped
      // connection logs nothing).
      console.error("Reply stream failed:", err);
      const reason = err.message || err.name || "unknown error";
      ReplyBody.render(bubble, "", "error", null, `${ReplyBody.FAILED_NOTICE} (${reason})`);
      if (inChannel) chatPage.channelReplyInFlight = false;
    } else if (bubble) {
      // Failed before anything was saved (e.g. an attachment refused): both bubbles would vanish on reload, so they
      // go now and the reason shows in an alert.
      userWrapper.remove();
      wrapper.remove();
      if (inChannel) chatPage.channelReplyInFlight = false;
      alert(err.message);
    } else {
      ChatBubbles.showSendError(userWrapper, err.message); // a plain message whose request failed
    }
  }
}

const messageSender = new MessageSender();
