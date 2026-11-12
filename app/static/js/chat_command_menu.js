/* The "/" menu of the chat box: typing "/" at the start of a message (or after other commands) lists the matching
   commands (ChatCommands, chat_commands.js) with what each does; arrows move, Enter or Tab picks, Escape closes, a
   click picks too. While it's open, Enter picks instead of sending (its keydown runs before chat.js's). */
class ChatCommandMenu {
  constructor(input) {
    this.input = input;
    this.items = [];
    this.active = 0;
    this.el = document.createElement("ul");
    this.el.className =
      "chat-command-menu hidden absolute bottom-full left-0 z-30 mb-2 w-96 max-w-full overflow-hidden rounded-lg " +
      "border border-slate-700 bg-slate-900 py-1 text-xs shadow-xl";
    this.el.setAttribute("role", "listbox");
    input.parentElement.appendChild(this.el);
    input.addEventListener("input", () => this.update());
    input.addEventListener("keydown", (event) => this.onKey(event), true);
    input.addEventListener("blur", () => setTimeout(() => this.close(), 150));
  }

  /* The "/word" being typed at the caret, when everything before it is commands: { start, typed } or null. */
  typing() {
    const before = this.input.value.slice(0, this.input.selectionStart);
    const match = before.match(/^((?:\s*\/[a-z][a-z_]*\s+)*)\s*\/([a-z_]*)$/i);
    if (!match) return null;
    const earlier = ChatCommands.leading(match[1]).commands.length;
    const words = (match[1].match(/\//g) || []).length;
    if (earlier !== words) return null; // an earlier "/word" isn't a command: plain text
    return { start: before.lastIndexOf("/"), typed: match[2].toLowerCase() };
  }

  update() {
    const typing = this.typing();
    if (!typing) return this.close();
    const already = ChatCommands.leading(this.input.value).commands;
    this.items = ChatCommands.list.filter(
      (c) => !already.includes(c) && (c.name.startsWith(typing.typed) || (c.aliases || []).some((a) => a.startsWith(typing.typed)))
    );
    if (!this.items.length) return this.close();
    this.active = Math.min(this.active, this.items.length - 1);
    this.render();
  }

  render() {
    this.el.innerHTML = "";
    this.items.forEach((command, index) => {
      const item = document.createElement("li");
      item.setAttribute("role", "option");
      item.className =
        "flex cursor-pointer flex-col px-3 py-1 " + (index === this.active ? "bg-slate-800" : "hover:bg-slate-800/60");
      const needs = command.needs ? ` · needs ${command.needs === "image" ? "an image" : "a file"}` : "";
      item.innerHTML =
        `<span class="font-mono text-slate-100">/${escapeHtml(command.name)}</span>` +
        `<span class="text-[11px] leading-tight text-slate-400">${escapeHtml(command.description)}${escapeHtml(needs)}</span>`;
      item.addEventListener("mousedown", (event) => {
        event.preventDefault(); // keep the box focused
        this.pick(command);
      });
      this.el.appendChild(item);
    });
    this.el.classList.remove("hidden");
  }

  onKey(event) {
    if (this.el.classList.contains("hidden")) return;
    const moves = { ArrowDown: 1, ArrowUp: -1 };
    if (event.key in moves) {
      this.active = (this.active + moves[event.key] + this.items.length) % this.items.length;
      this.render();
    } else if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
      this.pick(this.items[this.active]);
    } else if (event.key === "Escape") {
      this.close();
    } else {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation(); // chat.js would send the message on Enter
  }

  pick(command) {
    const typing = this.typing();
    if (!typing || !command) return this.close();
    const value = this.input.value;
    const caret = this.input.selectionStart;
    const inserted = `/${command.name} `;
    this.input.value = value.slice(0, typing.start) + inserted + value.slice(caret).replace(/^[a-z_]*\s*/i, "");
    const at = typing.start + inserted.length;
    this.input.setSelectionRange(at, at);
    this.close();
    this.input.dispatchEvent(new Event("input")); // resize, text direction, the attach hint
  }

  close() {
    this.el.classList.add("hidden");
    this.active = 0;
  }
}

const chatCommandInput = document.getElementById("chat-input");
if (chatCommandInput) new ChatCommandMenu(chatCommandInput);
