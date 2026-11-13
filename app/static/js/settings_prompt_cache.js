/* Admin settings > Inference > Prompt cache (/api/settings/prompt-cache): the layout of notes and skills, and the
   fields of the chosen one (the others are hidden). Uses api from app.js. */
class PromptCacheSetting {
  static URL = "/api/settings/prompt-cache";
  static NUMBERS = {
    max_updates: "#prompt-cache-max-updates",
    max_update_chars: "#prompt-cache-max-update-chars",
    load_above: "#prompt-cache-load-above",
    max_loaded: "#prompt-cache-max-loaded",
    min_block_tokens: "#prompt-cache-min-block",
  };

  constructor(root) {
    this.root = root;
    this.modes = [...root.querySelectorAll('input[name="prompt-cache-mode"]')];
    this.fields = Object.fromEntries(
      Object.entries(PromptCacheSetting.NUMBERS).map(([key, selector]) => [key, root.querySelector(selector)])
    );
    this.status = root.querySelector("#prompt-cache-status");
    this.modes.forEach((radio) => radio.addEventListener("change", () => this.showFields()));
    root.querySelector("#prompt-cache-save-btn").addEventListener("click", () => this.save());
    this.load();
  }

  get mode() {
    return (this.modes.find((radio) => radio.checked) || {}).value || "ordered";
  }

  showFields() {
    this.root.querySelectorAll("[data-mode-fields]").forEach((box) => {
      box.classList.toggle("hidden", box.dataset.modeFields !== this.mode);
    });
  }

  show(setting) {
    this.modes.forEach((radio) => (radio.checked = radio.value === setting.mode));
    Object.entries(this.fields).forEach(([key, input]) => (input.value = setting[key]));
    this.showFields();
  }

  async load() {
    try {
      this.show(await api(PromptCacheSetting.URL));
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  async save() {
    this.status.textContent = "Saving…";
    const body = { mode: this.mode };
    Object.entries(this.fields).forEach(([key, input]) => (body[key] = Number(input.value)));
    try {
      this.show(await api(PromptCacheSetting.URL, { method: "PUT", body: JSON.stringify(body) }));
      this.status.textContent = "Saved";
    } catch (err) {
      this.status.textContent = `Not saved: ${err.message}`;
    }
  }
}

const promptCachePanelEl = document.getElementById("prompt-cache-panel");
if (promptCachePanelEl) PageViews.whenShown(promptCachePanelEl, () => new PromptCacheSetting(promptCachePanelEl));
