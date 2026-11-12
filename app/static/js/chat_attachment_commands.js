/* Chat composer attachments: checks each picked file with the server (POST /api/chat/attachments/check), says why a
   rejected one can't be read, and puts the command for each attached kind in the message box (/describe for an image,
   /summarize for documents, both for a mix: ChatCommands.forKind), so a file can be sent without typing. The server
   expands the command (app/services/chat_commands.py). */
class AttachmentCommands {
  static URL = "/api/chat/attachments/check";
  static autoText = ""; // the command this script put in the box, cleared only while unchanged
  static warnings = []; // the last check's long-file warnings, shown while files are attached

  /* { accepted, rejected: [{ file, reason }], warnings: [text] }. If the check itself fails, every file passes: the
     server re-checks. With the chat's id, a long file comes back with how long the reply may take to start. */
  static async check(files, conversationId = null) {
    const none = { accepted: files, rejected: [], warnings: [] };
    if (!files.length) return none;
    const form = new FormData();
    for (const file of files) form.append("files", file);
    if (conversationId) form.append("conversation_id", conversationId);
    try {
      const response = await fetch(AttachmentCommands.URL, { method: "POST", body: form });
      if (!response.ok) return none;
      const verdicts = (await response.json()).files;
      const accepted = [];
      const rejected = [];
      files.forEach((file, i) => (verdicts[i]?.ok === false ? rejected.push({ file, reason: verdicts[i].reason }) : accepted.push(file)));
      const warnings = verdicts.filter((v) => v?.ok && v.warning).map((v) => v.warning);
      return { accepted, rejected, warnings };
    } catch (_err) {
      return none;
    }
  }

  /* The command for each kind attached, images first ("" with no files): "/describe /summarize" for a mix. */
  static command(files) {
    const kinds = ["image", "text"].filter((kind) => files.some((f) => ChatCommands.kindOf(f) === kind));
    return kinds.map((kind) => ChatCommands.forKind(kind)).filter(Boolean).map((c) => `/${c.name}`).join(" ");
  }

  /* Sets the box to the command for `files`, unless the user typed something of their own. */
  static prefill(input, files) {
    const current = input.value.trim();
    if (current && current !== AttachmentCommands.autoText) return;
    const command = AttachmentCommands.command(files);
    input.value = command ? `${command} ` : "";
    AttachmentCommands.autoText = command;
    input.dispatchEvent(new Event("input")); // resize, text direction
    if (command) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }

  /* While the box holds only commands: what sending it does, and the other forms ("/describe_short"...). */
  static hint(text) {
    const { commands, rest } = ChatCommands.leading(text);
    if (!commands.length || rest) return null;
    const typed = commands.map((c) => `/${c.name}`).join(" ");
    const what = commands.map((c) => c.hint || c.description).join(" and ");
    const others = commands.flatMap((c) => ChatCommands.siblings(c)).filter((c) => !commands.includes(c));
    const also = others.length
      ? ` Also: ${others.map((c) => `<span class="font-mono">/${escapeHtml(c.name)}</span>`).join(", ")}.`
      : "";
    return `Send <span class="font-mono">${escapeHtml(typed)}</span> to ${escapeHtml(what)}, or add your own question after it.${also}`;
  }

  static reset() {
    AttachmentCommands.autoText = "";
  }

  /* Plain-words reasons for rejected files, how long a long file may take, and a hint while a command waits. */
  static showNotice(el, rejected, files, input, warnings = null) {
    if (warnings) AttachmentCommands.warnings = [...AttachmentCommands.warnings, ...warnings];
    if (!files.length) AttachmentCommands.warnings = [];
    const lines = rejected.map((r) => `<li class="text-warning-400">${escapeHtml(r.reason)}</li>`);
    lines.push(...AttachmentCommands.warnings.map((w) => `<li class="text-warning-400">${escapeHtml(w)}</li>`));
    const hint = files.length ? AttachmentCommands.hint(input.value) : null;
    if (hint) lines.push(`<li class="text-slate-500">${hint}</li>`);
    el.innerHTML = lines.join("");
    el.classList.toggle("hidden", !lines.length);
  }
}
