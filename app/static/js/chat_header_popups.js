/* Header popups (export menu, model picker, note editor, reasoning confirm) open under the badge that opened them,
   not at one fixed corner. Each is an absolute child of <main> marked "top-14" (chat.html, chat_thinking.js). */
class HeaderPopups {
  static GAP = 6; // px between the badge and its popup
  static EDGE = 16; // px kept free at the sides of the chat

  constructor(header, main) {
    this.anchor = null;
    this.main = main;
    header.addEventListener("click", (event) => (this.anchor = event.target.closest("button") || this.anchor), true);
    new MutationObserver((changes) => changes.forEach((c) => this.onChange(c.target))).observe(main, {
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  onChange(popup) {
    const isPopup = popup.parentElement === this.main && popup.classList.contains("top-14");
    if (isPopup && !popup.classList.contains("hidden") && this.anchor && popup.dataset.placedFor !== "open") {
      popup.dataset.placedFor = "open";
      this.place(popup, this.anchor);
    } else if (isPopup && popup.classList.contains("hidden")) {
      delete popup.dataset.placedFor;
    }
  }

  /* Left edge under the badge; a popup that would cross the chat's right side lines up with the badge's right
     edge instead. */
  place(popup, anchor) {
    const area = this.main.getBoundingClientRect();
    const badge = anchor.getBoundingClientRect();
    const width = popup.offsetWidth;
    let left = badge.left - area.left;
    if (left + width > area.width - HeaderPopups.EDGE) left = badge.right - area.left - width;
    left = Math.max(HeaderPopups.EDGE, Math.min(left, area.width - width - HeaderPopups.EDGE));
    popup.style.left = `${left}px`;
    popup.style.right = "auto";
    popup.style.top = `${badge.bottom - area.top + HeaderPopups.GAP}px`;
  }
}

const headerPopups = new HeaderPopups(document.querySelector("main > header"), document.querySelector("main"));
