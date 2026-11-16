/* The "/" menu of the chat box: typing "/" at the start of a message (or after other commands) lists the matching
   commands (ChatCommands, chat_commands.js) with what each does; arrows move, Enter or Tab picks, Escape closes, a
   click picks too. While it's open, Enter picks instead of sending (its keydown runs before chat.js's).
   /use_skill too, when the Prompt cache's Short index picks skills by command (chat.js midChatChanges.skill_command)
   and the chat has skills (chat_skills.js): at the start or after the words at the end; "/use_skill " then lists the
   chat's skills, and picking one puts /use_skill "<name>" in the message (app/services/chat_skill_command.py). */
const USE_SKILL = { name: "use_skill", description: "Use one of this chat's skills for this message", aliases: [] };
class ChatCommandMenu {
  constructor(input) {
    this.input = input;
    this.items = [];
    this.active = 0;
    this.el = document.createElement("ul");
    this.el.className =
      "chat-command-menu hidden absolute bottom-full left-0 z-30 mb-2 w-96 max-w-full max-h-72 overflow-y-auto rounded-lg " +
      "border border-slate-700 bg-slate-900 py-1 text-xs shadow-xl";
    this.el.setAttribute("role", "listbox");
    input.parentElement.appendChild(this.el);
    input.addEventListener("input", () => this.update());
    input.addEventListener("keydown", (event) => this.onKey(event), true);
    input.addEventListener("blur", () => setTimeout(() => this.close(), 150));
    // The user's whole skill list arrived (chat_skills.js libraryNames): redraw if they're typing a command.
    document.addEventListener("chat-skills-library", () => document.activeElement === input && this.update());
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

  /* The skills /use_skill offers when it's on: the chat's, or every one the user may use when the chat has none
     (picking one only adds the badge; the chat's own skills don't change). [] when it's off. */
  skills() {
    const on = typeof midChatChanges !== "undefined" && midChatChanges.skill_command;
    if (!on || typeof chatSkills === "undefined") return [];
    const chosen = chatSkills.chosen.map((s) => s.name);
    return chosen.length ? chosen : chatSkills.libraryNames();
  }

  /* /use_skill being typed at the caret: { start, typed, naming } (naming: the skill's name after "/use_skill "). */
  skillTyping() {
    if (!this.skills().length) return null;
    const before = this.input.value.slice(0, this.input.selectionStart);
    const naming = before.match(/(?:^|\s)(\/use_skill\s+"?([^"\n]*))$/i);
    if (naming) return { start: before.length - naming[1].length, typed: naming[2].toLowerCase(), naming: true };
    const word = before.match(/(?:^|\s)(\/([a-z_]*))$/i);
    if (word && "use_skill".startsWith(word[2].toLowerCase())) {
      return { start: before.length - word[1].length, typed: word[2].toLowerCase(), naming: false };
    }
    return null;
  }

  update() {
    const skill = this.skillTyping();
    if (skill?.naming) {
      this.items = this.skills()
        .filter((name) => name.toLowerCase().includes(skill.typed))
        .map((name) => ({ skill: name, name, description: "Use this skill for this message", aliases: [] }));
      return this.items.length ? this.show() : this.close();
    }
    const typing = this.typing();
    if (!typing) return skill ? this.offerUseSkill() : this.close(); // "/" after the words: only /use_skill
    const already = ChatCommands.leading(this.input.value).commands;
    this.items = ChatCommands.list.filter(
      (c) => !already.includes(c) && (c.name.startsWith(typing.typed) || (c.aliases || []).some((a) => a.startsWith(typing.typed)))
    );
    if (this.skills().length && !already.length && USE_SKILL.name.startsWith(typing.typed)) this.items.push(USE_SKILL);
    if (!this.items.length) return this.close();
    this.show();
  }

  /* "/" after the words at the end of a message: only /use_skill fits there. */
  offerUseSkill() {
    this.items = [USE_SKILL];
    this.show();
  }

  show() {
    this.active = Math.min(this.active, this.items.length - 1);
    this.render();
  }

  render() {
    this.el.innerHTML = "";
    this.items.forEach((command, index) => {
      const item = document.createElement("li");
      item.setAttribute("role", "option");
      item.className = "flex cursor-pointer flex-col border-l-2 px-3 py-1";
      const needs = command.needs ? ` · needs ${command.needs === "image" ? "an image" : "a file"}` : "";
      const label = command.skill ? escapeHtml(command.skill) : `/${escapeHtml(command.name)}`;
      item.innerHTML =
        `<span class="${command.skill ? "" : "font-mono "}text-slate-100">${label}</span>` +
        `<span class="text-[11px] leading-tight text-slate-400">${escapeHtml(command.description)}${escapeHtml(needs)}</span>`;
      item.addEventListener("mouseenter", () => this.highlight(index));
      item.addEventListener("mousedown", (event) => {
        event.preventDefault(); // keep the box focused
        this.pick(command);
      });
      this.el.appendChild(item);
    });
    this.highlight(this.active);
    this.el.classList.remove("hidden");
    this.el.children[this.active]?.scrollIntoView({ block: "nearest" }); // a long skill list: keep the pick in view
  }

  /* One marked row for mouse and keys alike, in the brand color so it shows in light and dark themes. */
  highlight(index) {
    this.active = index;
    [...this.el.children].forEach((item, i) => {
      const on = i === index;
      item.classList.toggle("bg-brand-500/25", on);
      item.classList.toggle("border-brand-500", on);
      item.classList.toggle("border-transparent", !on);
    });
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
    const skill = this.skillTyping();
    if (command && (command.skill || (command === USE_SKILL && skill))) return this.pickSkill(command, skill);
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

  /* /use_skill, then its name: replaces what was typed from the "/" to the caret. A picked name becomes the badge
     above the box (chat_skill_chip.js), not text in it. */
  pickSkill(command, skill) {
    const value = this.input.value;
    const caret = this.input.selectionStart;
    const badge = command.skill && typeof skillChip !== "undefined";
    if (badge) skillChip.set(command.skill);
    const inserted = badge ? "" : command.skill ? `/use_skill "${command.skill}" ` : "/use_skill ";
    this.input.value = value.slice(0, skill.start) + inserted + value.slice(caret);
    const at = skill.start + inserted.length;
    this.input.setSelectionRange(at, at);
    this.close();
    this.input.dispatchEvent(new Event("input")); // "/use_skill " lists the skills next
  }

  close() {
    this.el.classList.add("hidden");
    this.active = 0;
  }
}

const chatCommandInput = document.getElementById("chat-input");
if (chatCommandInput) new ChatCommandMenu(chatCommandInput);
