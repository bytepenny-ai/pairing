/* The chat commands a message can start with (/describe, /summarize and their short and long forms), as the server
   lists them (GET /api/chat/commands, app/services/chat_command_catalog.py): the "/" menu (chat_command_menu.js) and
   the command put in the box when a file is attached (chat_attachment_commands.js) read them here, so a new command
   needs no change on this side. Until the list arrives, the two attach commands below stand in. Uses api from app.js. */
class ChatCommands {
  static URL = "/api/chat/commands";
  static FALLBACK = [
    { name: "describe", description: "Describe the attached image", needs: "image", prefill_for: "image", hint: "describe the image", aliases: [] },
    { name: "summarize", description: "Summarize the attached files", needs: "text", prefill_for: "text", hint: "summarize the files", aliases: [] },
  ];
  static list = ChatCommands.FALLBACK;
  static loading = null;

  static load() {
    ChatCommands.loading ??= api(ChatCommands.URL)
      .then((reply) => (ChatCommands.list = reply.commands))
      .catch(() => ChatCommands.list);
    return ChatCommands.loading;
  }

  /* A command by name or alias ("summarise"), or null. */
  static get(name) {
    const wanted = (name || "").toLowerCase();
    return ChatCommands.list.find((c) => c.name === wanted || (c.aliases || []).includes(wanted)) || null;
  }

  /* The command put in the box when a file of this kind ("image" or "text") is attached. */
  static forKind(kind) {
    return ChatCommands.list.find((c) => c.prefill_for === kind) || null;
  }

  static kindOf(file) {
    return file.type.startsWith("image/") ? "image" : "text";
  }

  /* The commands `text` starts with, and the words after them: { commands, rest }. */
  static leading(text) {
    const commands = [];
    let rest = text || "";
    let match;
    while ((match = rest.match(/^\s*\/([a-z][a-z_]*)\b[ \t]*([\s\S]*)$/i))) {
      const command = ChatCommands.get(match[1]);
      if (!command) break;
      if (!commands.includes(command)) commands.push(command);
      rest = match[2];
    }
    return { commands, rest: commands.length ? rest.trim() : text };
  }

  /* The other commands working on the same kind of file ("/describe_short", "/describe_long" for /describe). */
  static siblings(command) {
    return ChatCommands.list.filter((c) => c !== command && c.needs && c.needs === command.needs);
  }
}

ChatCommands.load();
