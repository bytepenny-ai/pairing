/* The message composer (_chat_composer.html): the text box, Send and "Ask AI", the emoji picker and the files picked
to attach to the next message. Sending itself is chat_send.js. */
class ChatComposer {
  // 50 common, simple emoji (faces, gestures, hearts), 8 per row in display order.
  static EMOJI_CHOICES = [
    "😀", "😃", "😄", "😁", "😆", "😊", "🙂", "😉", "😍", "🥰",
    "😘", "🤗", "🤔", "😴", "😋", "😜", "🤩", "😎", "🥳", "😇",
    "🙃", "😢", "😭", "😡", "😱", "😨", "😅", "🤣", "😬", "🥺",
    "👍", "👎", "👏", "🙌", "🙏", "👋", "💪", "✌️", "🤝", "👌",
    "❤️", "🧡", "💛", "💚", "💙", "💜", "💕", "⭐", "✨", "🎉",
  ];
  // Per-message caps, kept in sync by hand with app.config MAX_ATTACHMENT_DOCUMENTS/IMAGES; the server checks again.
  static MAX_DOCUMENTS = 5;
  static MAX_IMAGES = 1;
  static MAX_INPUT_HEIGHT_PX = 200;

  constructor() {
    this.form = document.getElementById("chat-form");
    this.input = document.getElementById("chat-input");
    this.sendBtn = document.getElementById("send-btn");
    this.askAiBtn = document.getElementById("ask-ai-btn");
    this.attachmentInput = document.getElementById("attachment-input");
    this.previewEl = document.getElementById("attachment-preview");
    this.noticeEl = document.getElementById("attachment-notice");
    // The files for the next send; the source of truth (the file input is cleared after each pick).
    this.pending = [];
    this.initEmojiPicker();
    this.initInput();
    document.getElementById("attach-btn").addEventListener("click", () => this.attachmentInput.click());
    this.attachmentInput.addEventListener("change", () => this.onFilesPicked());
  }

  initInput() {
    // Grows with its content up to a max height, and follows the typing direction (Hebrew/Arabic).
    this.input.addEventListener("input", () => {
      this.input.style.height = "auto";
      this.input.style.height = Math.min(this.input.scrollHeight, ChatComposer.MAX_INPUT_HEIGHT_PX) + "px";
      this.input.dir = detectTextDirection(this.input.value);
    });
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        this.form.requestSubmit();
      }
    });
    // Send in a channel posts without an AI reply (that is "Ask AI"); a personal chat always asks the AI.
    this.form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const id = chatPage.activeConversationId;
      await messageSender.send(!(id && chatPage.channels[id]));
    });
    this.askAiBtn.addEventListener("click", () => messageSender.send(true));
  }

  initEmojiPicker() {
    const button = document.getElementById("emoji-btn");
    const picker = document.getElementById("emoji-picker");
    if (picker.childElementCount === 0) {
      for (const emoji of ChatComposer.EMOJI_CHOICES) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = emoji;
        btn.className = "rounded-md p-1 text-lg leading-none hover:bg-slate-800 transition-colors";
        btn.addEventListener("click", () => this.insertAtCursor(emoji));
        picker.appendChild(btn);
      }
    }
    // Stays open to pick several in a row; closes on an outside click, Escape, or the emoji button again.
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      picker.classList.toggle("hidden");
    });
    document.addEventListener("click", (event) => {
      if (!picker.classList.contains("hidden") && !picker.contains(event.target) && event.target !== button) {
        picker.classList.add("hidden");
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") picker.classList.add("hidden");
    });
  }

  insertAtCursor(text) {
    const start = this.input.selectionStart ?? this.input.value.length;
    const end = this.input.selectionEnd ?? this.input.value.length;
    this.input.value = this.input.value.slice(0, start) + text + this.input.value.slice(end);
    const cursor = start + text.length;
    this.input.focus();
    this.input.setSelectionRange(cursor, cursor);
  }

  text() {
    return this.input.value.trim();
  }

  clearText() {
    this.input.value = "";
    this.input.style.height = "auto";
  }

  /* The files for this send, cleared from the composer at once so a file picked during the send isn't attached. */
  takeFiles() {
    const files = this.pending;
    this.clearFiles();
    return files;
  }

  clearFiles() {
    this.pending = [];
    this.attachmentInput.value = "";
    this.previewEl.replaceChildren();
    this.previewEl.classList.add("hidden");
    AttachmentCommands.reset();
    AttachmentCommands.showNotice(this.noticeEl, [], [], this.input);
  }

  async onFilesPicked() {
    // Only the new picks are checked; a file no model can read is dropped with its reason.
    const fresh = Array.from(this.attachmentInput.files || []);
    this.attachmentInput.value = "";
    const { accepted, rejected, warnings } = await AttachmentCommands.check(fresh, chatPage.activeConversationId);
    // Merged with earlier picks: the input reports only this dialog's selection.
    const picked = [...this.pending, ...accepted];
    const images = picked.filter((f) => f.type.startsWith("image/"));
    const documents = picked.filter((f) => !f.type.startsWith("image/"));
    if (images.length > ChatComposer.MAX_IMAGES || documents.length > ChatComposer.MAX_DOCUMENTS) {
      alert(`Up to ${ChatComposer.MAX_IMAGES} image and ${ChatComposer.MAX_DOCUMENTS} document files per message.`);
    }
    this.pending = [...images.slice(0, ChatComposer.MAX_IMAGES), ...documents.slice(0, ChatComposer.MAX_DOCUMENTS)];
    this.renderPreview();
    AttachmentCommands.prefill(this.input, this.pending);
    AttachmentCommands.showNotice(this.noticeEl, rejected, this.pending, this.input, warnings);
  }

  removeFile(file) {
    this.pending = this.pending.filter((f) => f !== file);
    this.renderPreview();
    AttachmentCommands.prefill(this.input, this.pending); // drops the command if no file is left for it
    AttachmentCommands.showNotice(this.noticeEl, [], this.pending, this.input);
  }

  /* One chip per picked file, each with an "×" to drop it. */
  renderPreview() {
    this.previewEl.replaceChildren();
    this.previewEl.classList.toggle("hidden", this.pending.length === 0);
    for (const file of this.pending) {
      const chip = document.createElement("div");
      chip.className =
        "flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300";
      const name = document.createElement("span");
      name.className = "truncate max-w-[16rem]";
      name.textContent = file.name;
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "shrink-0 text-slate-500 hover:text-red-400";
      clear.textContent = "×";
      clear.addEventListener("click", () => this.removeFile(file));
      chip.append(name, clear);
      this.previewEl.appendChild(chip);
    }
  }

  /* "Ask AI" is off while any member's reply is generating in the channel (the server answers 409 otherwise). */
  setAskAiBusy(busy) {
    this.askAiBtn.disabled = busy;
    this.askAiBtn.title = busy ? "The AI is already replying to another message in this channel" : "";
  }
}

const chatComposer = new ChatComposer();
