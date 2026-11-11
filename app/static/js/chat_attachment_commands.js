/* Chat composer attachments: checks each picked file with the server (POST /api/chat/attachments/check), says why a
   rejected one can't be read, and puts /describe (an image), /summarize (documents) or both in the message box, so a
   file can be sent without typing. The server expands the command (app/services/chat_commands.py). */
class AttachmentCommands {
  static URL = "/api/chat/attachments/check";
  static autoText = ""; // the command this script put in the box, cleared only while unchanged

  /* { accepted, rejected: [{ file, reason }] }. If the check itself fails, every file passes: the server re-checks. */
  static async check(files) {
    if (!files.length) return { accepted: [], rejected: [] };
    const form = new FormData();
    for (const file of files) form.append("files", file);
    try {
      const response = await fetch(AttachmentCommands.URL, { method: "POST", body: form });
      if (!response.ok) return { accepted: files, rejected: [] };
      const verdicts = (await response.json()).files;
      const accepted = [];
      const rejected = [];
      files.forEach((file, i) => (verdicts[i]?.ok === false ? rejected.push({ file, reason: verdicts[i].reason }) : accepted.push(file)));
      return { accepted, rejected };
    } catch (_err) {
      return { accepted: files, rejected: [] };
    }
  }

  /* "/describe" for an image, "/summarize" for documents, both for a mix ("" with no files). */
  static command(files) {
    const hasImage = files.some((f) => f.type.startsWith("image/"));
    const hasDocument = files.some((f) => !f.type.startsWith("image/"));
    return [hasImage && "/describe", hasDocument && "/summarize"].filter(Boolean).join(" ");
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

  static reset() {
    AttachmentCommands.autoText = "";
  }

  /* Plain-words reasons for rejected files, and a hint while a command waits in the box. */
  static showNotice(el, rejected, files, input) {
    const lines = rejected.map((r) => `<li class="text-warning-400">${escapeHtml(r.reason)}</li>`);
    const command = AttachmentCommands.command(files);
    if (command && input.value.trim() === command) {
      const documents = files.filter((f) => !f.type.startsWith("image/")).length;
      const parts = [command.includes("/describe") && "describe the image", documents && `summarize the file${documents > 1 ? "s" : ""}`];
      const what = parts.filter(Boolean).join(" and ");
      lines.push(`<li class="text-slate-500">Send <span class="font-mono">${command}</span> to ${what}, or add your own question after it.</li>`);
    }
    el.innerHTML = lines.join("");
    el.classList.toggle("hidden", !lines.length);
  }
}
