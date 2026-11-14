/* The Knowledge page's small dialog (settings/knowledge.html #kb-dialog): a folder name, where to move files, or a
 * confirmation. `ask` runs `submit(value)` on OK and keeps the dialog open with its error (e.g. "You already have a
 * folder named …") until it succeeds or the person cancels. */
class KnowledgeDialog {
  constructor(root) {
    this.root = root;
    this.field = (name) => root.querySelector(`[data-kb="${name}"]`);
    this.form = this.field("dialog-form");
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.confirm();
    });
    this.field("dialog-cancel").addEventListener("click", () => this.finish(false));
    root.addEventListener("click", (event) => event.target === root && this.finish(false));
    document.addEventListener("keydown", (event) => event.key === "Escape" && this.isOpen() && this.finish(false));
  }

  /* { title, text, ok, danger, input: {value, placeholder}, options: [{value, label}], submit } -> true once done. */
  ask({ title, text = "", ok = "OK", danger = false, input = null, options = null, submit = async () => null }) {
    this.field("dialog-title").textContent = title;
    this.field("dialog-text").textContent = text;
    this.field("dialog-error").textContent = "";
    const okBtn = this.field("dialog-ok");
    okBtn.textContent = ok;
    // Danger: tinted red with red text, readable in light themes too (their red scale flips, so solid red went pale).
    for (const name of ["bg-red-500/15", "text-red-400", "border", "border-red-500/50", "hover:bg-red-500/25"]) okBtn.classList.toggle(name, danger);
    for (const name of ["bg-brand-600", "hover:bg-brand-500", "text-white"]) okBtn.classList.toggle(name, !danger);
    const inputEl = this.field("dialog-input");
    const selectEl = this.field("dialog-select");
    inputEl.classList.toggle("hidden", !input);
    selectEl.classList.toggle("hidden", !options);
    inputEl.value = input?.value || "";
    inputEl.placeholder = input?.placeholder || "";
    selectEl.innerHTML = (options || [])
      .map((o) => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`)
      .join("");
    this.read = () => (input ? inputEl.value : options ? selectEl.value : true);
    this.submit = submit;
    this.root.classList.remove("hidden");
    (input ? inputEl : options ? selectEl : okBtn).focus();
    if (input) inputEl.select();
    return new Promise((resolve) => (this.resolve = resolve));
  }

  async confirm() {
    const okBtn = this.field("dialog-ok");
    okBtn.disabled = true;
    try {
      const error = await this.submit(this.read());
      if (error) this.field("dialog-error").textContent = error;
      else this.finish(true);
    } catch (err) {
      this.field("dialog-error").textContent = err.message;
    } finally {
      okBtn.disabled = false;
    }
  }

  isOpen() {
    return !this.root.classList.contains("hidden");
  }

  finish(done) {
    this.root.classList.add("hidden");
    this.resolve?.(done);
    this.resolve = null;
  }
}
