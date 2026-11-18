/*
 * One send's request (POST /api/chat/{id}/stream) and its Server-Sent Events, read as they arrive so the reply "types"
 * live. EventSource is out: it supports only GET.
 *
 * `wrapper`/`bubble` are the reply bubble (ChatBubbles.create), null when `askAi` is false: a plain channel message gets
 * no reply. Both bubbles are tagged with their message ids from the first events and added to chatPage.liveMessageIds,
 * so the poll and live watch leave them alone; an untagged user message was once shown twice after a send.
 */
class ReplyStream {
  constructor(conversationId, content, askAi, userWrapper, wrapper, bubble, files) {
    this.conversationId = conversationId;
    this.content = content;
    this.askAi = askAi;
    this.userWrapper = userWrapper;
    this.wrapper = wrapper;
    this.bubble = bubble;
    this.files = files;
    this.fullText = "";
    // A channel never gets a generated title: its header and sidebar show the channel's name.
    this.isChannel = !!chatPage.channels[conversationId];
  }

  /* Sends the message and reads the reply to its end. `registerAbortable(xhr)` lets leaving the chat abort it. */
  async run(registerAbortable) {
    // FormData, not JSON: the browser sets the multipart boundary. "attachments" repeats per file.
    const formData = new FormData();
    formData.append("content", this.content);
    formData.append("ask_ai", this.askAi);
    for (const file of this.files) formData.append("attachments", file);
    const { xhr, chunks } = XhrStream.start(`/api/chat/${this.conversationId}/stream`, formData);
    registerAbortable(xhr);
    if (this.files.length > 0) UploadProgress.follow(xhr, this.userWrapper);
    await XhrStream.whenAccepted(xhr);
    UploadProgress.remove(this.userWrapper);

    let buffer = "";
    for await (const newText of chunks) {
      // Frames end with a blank line, and one delta can hold zero, one or several of them.
      buffer += newText;
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith("data:")) continue;
        if (this.handle(JSON.parse(line.slice("data:".length).trim()))) return;
      }
    }
  }

  /* One event; true when the reply is over. */
  handle(payload) {
    this.tag(payload);
    // A file or excerpts cut to fit the context window (turn_context_fit.py); a display problem must not end the reply.
    if (payload.notice) {
      try {
        ChatBubbles.showNotice(this.userWrapper, payload.notice);
      } catch (err) {
        console.error("Could not show the notice:", err);
      }
    }
    if (payload.deleted) {
      // A channel manager deleted this reply while it was generating: remove it now, as the deleting tab does.
      if (this.bubble) this.wrapper.remove();
      if (this.isChannel) chatPage.setChannelReplyInFlight(false);
      return true;
    }
    if (payload.error) {
      // As a reload shows it: the streamed text stays, with the real reason below.
      if (!this.bubble) throw new Error(payload.error);
      ReplyBody.render(this.bubble, this.fullText, "error", null, payload.error);
      return true;
    }
    // A title arrives early ("simple" mode) or with "done" ("smart" mode, still "New chat" then). For a channel it is
    // the stale placeholder.
    if (payload.title && !this.isChannel) chatSidebar.showTitle(this.conversationId, payload.title);
    this.showProgress(payload);
    if (payload.done) {
      this.finish(payload);
      return true;
    }
    return false;
  }

  /* Tags both bubbles with their message ids the first time they appear, before any error check: an instant failure's
  first event can be the error, and a later reconcile must find these nodes. */
  tag(payload) {
    // The first event of every send (build_reply_stream): the user message's id. Its delete and share controls are
    // added here too, since the poll and live watch skip messages this tab drives.
    if (payload.user_message_id && !this.userWrapper.dataset.messageId) {
      this.userWrapper.dataset.messageId = payload.user_message_id;
      chatPage.liveMessageIds.add(payload.user_message_id);
      chatBubbles.attachDeleteButton(this.userWrapper, payload.user_message_id);
      ChannelShare.decorate(this.userWrapper, payload.user_message_id, "user");
    }
    if (this.bubble && payload.message_id && !this.wrapper.dataset.messageId) {
      this.wrapper.dataset.messageId = payload.message_id;
      chatPage.liveMessageIds.add(payload.message_id);
      chatBubbles.attachDeleteButton(this.wrapper, payload.message_id);
    }
  }

  /* Everything before and while the reply is written: knowledge search, reading progress, tools, reasoning, text. */
  showProgress(payload) {
    const bubble = this.bubble;
    // Excerpts go into the prompt: the vector space shows until the reply starts.
    if (bubble && payload.retrieval) {
      VectorSpace.cover(this.userWrapper, "knowledge", payload.retrieval);
      VectorSpace.bestMatch(this.userWrapper, payload.retrieval_best);
    }
    if (payload.read_progress != null) VectorSpace.progress(this.userWrapper, payload.read_progress);
    if (!bubble) return;
    if (payload.tool) ToolBlocks.add(bubble, payload.tool);
    if (payload.reasoning) {
      ReasoningSteps.set(bubble, payload.reasoning);
      ReplyBody.render(bubble, this.fullText, "streaming");
    }
    if (payload.read_progress != null || payload.compacting) {
      chatLive.applyProgress(bubble, payload);
      ReplyBody.render(bubble, this.fullText, "streaming");
    }
    if (payload.chunk) {
      VectorSpace.reveal(this.userWrapper); // thinking is over: the message comes back
      this.fullText += payload.chunk;
      ReplyBody.render(bubble, this.fullText, "streaming");
      chatScroll.follow();
    }
  }

  /* "done" comes before "smart" title mode's model call, so the reply doesn't wait for the title. */
  finish(payload) {
    const { bubble, wrapper } = this;
    if (bubble) ReplyBody.render(bubble, this.fullText, "complete", payload.sources);
    if (wrapper) ChatBubbles.setTime(wrapper, new Date().toISOString()); // a reply's time is when it finished
    ReplyStatsLine.show(wrapper, payload.stats);
    if (bubble && wrapper.dataset.messageId) ChannelShare.decorate(wrapper, wrapper.dataset.messageId, "assistant");
    if (this.isChannel && this.askAi) chatPage.setChannelReplyInFlight(false);
    if (!this.isChannel && payload.title === "New chat") chatSidebar.pollForTitle(this.conversationId);
  }
}
