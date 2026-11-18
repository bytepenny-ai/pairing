/* What a message bubble shows inside: the reply text, a waiting label, a failure notice, the Knowledge base sources
and the attached files. Used for every render (history, poll, live events, the sender's own stream), so a reply reads
the same however you arrive. */
class ReplyBody {
  // Shown in place of a failed or interrupted reply's content; partial content stays above it.
  static FAILED_NOTICE = "⚠️ This reply didn't finish — generation failed or was interrupted.";
  static IMAGE_SWITCH_NOTE = "_Looking at the image again…_"; // image_fallback_stream.SWITCH_NOTE, trimmed

  /*
   * Renders a reply's body from its content and status (Message.status): typing dots (streaming, nothing yet), the
   * text (streaming or complete), or the text with a failure notice (status "error"). `errorText` replaces the generic
   * FAILED_NOTICE with the real reason (Message.error_message, or a live event's `error`).
   */
  static render(bubble, content, status, sources, errorText) {
    // The chat's model handed over to the vision model (image_fallback_stream.py): a wait, until its words arrive.
    const lookingAgain = status === "streaming" && content?.trim() === ReplyBody.IMAGE_SWITCH_NOTE;
    if (status === "streaming" && (!content || lookingAgain)) {
      bubble.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
      // Says what the wait is: read progress, the reasoning stage, or "Thinking…" until the first words arrive.
      const waiting = lookingAgain
        ? "Looking at the image again…"
        : ReadProgress.label(bubble) || ReasoningSteps.label(bubble, thinkingChip.on ? "Reasoning…" : "Thinking…");
      bubble.insertAdjacentHTML("beforeend", `<span class="ml-2 text-xs text-slate-400">${waiting}</span>`);
      ToolBlocks.render(bubble);
      return;
    }
    MessageMarkdown.render(bubble, content);
    if (status === "error") {
      const notice = document.createElement("div");
      notice.className = "mt-2 pt-2 border-t border-white/10 text-xs text-red-400";
      notice.textContent = errorText || ReplyBody.FAILED_NOTICE;
      bubble.appendChild(notice);
    } else {
      ReplyBody.appendSources(bubble, sources);
      // The skill the message being answered asked for (/use_skill), under the reply like its sources.
      if (bubble._askedSkill && typeof SkillChip !== "undefined") bubble.appendChild(SkillChip.footer(bubble._askedSkill));
    }
    ToolBlocks.render(bubble);
  }

  /* The Knowledge base documents a reply drew on ({name, id, score}; older replies: a plain name), each with an id
  opening in the file viewer (GET /api/knowledge/files/{id}). After the final text: a later render replaces it. */
  static appendSources(bubble, sources) {
    if (!sources || sources.length === 0) return;
    const footer = document.createElement("div");
    footer.className = "mt-2 pt-2 border-t border-white/10 text-xs text-slate-400 flex flex-wrap items-center gap-x-3 gap-y-1";
    footer.appendChild(document.createTextNode("Sources:"));
    for (const source of sources) {
      const name = typeof source === "string" ? source : source.name;
      const item = document.createElement(source.id ? "a" : "span");
      item.textContent = "📄 " + name + (typeof source.score === "number" ? ` (score: ${source.score.toFixed(2)})` : "");
      if (source.id) {
        item.href = `/api/knowledge/files/${encodeURIComponent(source.id)}`;
        item.target = "_blank";
        item.rel = "noopener";
        item.className = "underline decoration-dotted hover:text-slate-200";
        if (ChatFileViewer.canShow(name)) {
          item.dataset.chatFile = name;
          item.title = "Click to view";
        }
      }
      footer.appendChild(item);
    }
    bubble.appendChild(footer);
  }

  /* A message's attachments (MessageOut.attachments): an image, or a file chip; a click opens either in
  chat_file_viewer.js. Call it after each render on the same bubble, which replaces its HTML. */
  static renderAttachments(bubble, message) {
    if (!message || !message.attachments) return;
    for (const attachment of message.attachments) {
      bubble.appendChild(attachment.type === "image" ? ReplyBody.image(attachment) : ReplyBody.fileChip(attachment));
    }
  }

  static image(attachment) {
    const img = document.createElement("img");
    img.src = attachment.url;
    img.alt = attachment.filename || "attachment";
    // Fits the bubble's width and 60% of the screen's height; a click enlarges it.
    img.className = "max-h-[60vh] max-w-full w-auto rounded-lg object-contain";
    // An <img> has no height until it loads: scroll again once its size is known.
    img.addEventListener("load", () => chatScroll.settle());
    const link = document.createElement("a");
    link.href = attachment.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = "Click to enlarge";
    link.dataset.chatFile = img.alt;
    link.className = "mt-2 block w-fit cursor-zoom-in";
    link.appendChild(img);
    return link;
  }

  static fileChip(attachment) {
    const chip = document.createElement("a");
    chip.href = attachment.url;
    chip.target = "_blank";
    chip.rel = "noopener";
    chip.className = "mt-2 flex items-center gap-1.5 text-xs underline decoration-dotted";
    chip.textContent = "📎 " + (attachment.filename || "attachment");
    if (ChatFileViewer.canShow(attachment.filename)) {
      chip.dataset.chatFile = attachment.filename;
      chip.title = "Click to view";
    }
    return chip;
  }
}
