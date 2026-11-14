/* The skill picked for the next message with /use_skill (chat_command_menu.js), shown as a small badge above the
   message box instead of command text, so typing stays undisturbed; its × removes it. On send, chat.js puts
   /use_skill "<name>" in front of the message (`withCommand`, read by app/services/chat_skill_command.py), and the
   badge clears; switching chats clears it too. */
class SkillChip {
  constructor(row) {
    this.row = row;
    this.name = "";
    row.addEventListener("click", (event) => {
      if (event.target.closest("[data-skill-chip-remove]")) {
        this.clear();
        document.getElementById("chat-input")?.focus();
      }
    });
  }

  set(name) {
    this.name = name;
    this.row.innerHTML =
      `<span class="inline-flex max-w-full items-center gap-1 rounded-full bg-brand-600 px-2 py-0.5 text-xs text-white" title="This skill is used for your next message">` +
      `<span aria-hidden="true">📚</span><span class="truncate">${escapeHtml(name)}</span>` +
      `<button type="button" data-skill-chip-remove aria-label="Remove the skill ${escapeHtml(name)}" title="Remove" class="ml-0.5 leading-none text-white/80 hover:text-white">×</button></span>`;
    this.row.classList.remove("hidden");
  }

  clear() {
    this.name = "";
    this.row.replaceChildren();
    this.row.classList.add("hidden");
  }

  /* A sent message's /use_skill "<name>" (anywhere, as app/services/chat_skill_command.py reads it): { skill, text }
     with the command taken out, so the bubble shows a badge instead (chat.js addMessageBubble); skill null without
     one. */
  static split(content) {
    const text = content || "";
    const match = text.match(/(?<![^\s])\/use_skill\s+"([^"\n]+)"/i);
    if (!match) return { skill: null, text };
    const left = text.slice(0, match.index).replace(/[ \t]+$/, "");
    const right = text.slice(match.index + match[0].length).replace(/^[ \t]+/, "");
    const joined = left && right && !left.endsWith("\n") ? `${left} ${right}` : left + right;
    return { skill: match[1], text: joined.trim() };
  }

  /* The badge at the top of a sent message's bubble (white on the bubble's brand colour). */
  static badge(name) {
    const el = document.createElement("div");
    el.className = "mb-1 inline-flex max-w-full items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-[11px] text-white";
    el.title = "The skill used for this message";
    el.innerHTML = `<span aria-hidden="true">📚</span><span class="truncate">${escapeHtml(name)}</span>`;
    return el;
  }

  /* The line under a reply naming the skill its message asked for, styled like the knowledge base's "Sources". */
  static footer(name) {
    const el = document.createElement("div");
    el.className = "mt-2 pt-2 border-t border-white/10 text-xs text-slate-400";
    el.textContent = `📚 Skill: ${name}`;
    return el;
  }

  /* The message as sent: with the picked skill's command in front (none picked: unchanged). */
  withCommand(text) {
    return this.name && text ? `/use_skill "${this.name}" ${text}` : text;
  }
}

const skillChipRow = document.getElementById("skill-chip");
const skillChip = skillChipRow ? new SkillChip(skillChipRow) : undefined;
