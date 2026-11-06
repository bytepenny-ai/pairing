/* Admin settings > System > "Reasoning": allow or block the chats' Reasoning option for everyone
(app/services/reasoning_setting.py). Reads/writes /api/settings/reasoning via api from app.js. */
class ReasoningSwitchForm {
  constructor(section) {
    this.select = section.querySelector("#reasoning-enabled");
    this.saveBtn = section.querySelector("#reasoning-save-btn");
    this.status = section.querySelector("#reasoning-status");
    this.saveBtn.addEventListener("click", () => this.save());
    this.load();
  }

  async load() {
    try {
      const { enabled } = await api("/api/settings/reasoning");
      this.select.value = enabled ? "on" : "off";
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  async save() {
    this.saveBtn.disabled = true;
    this.status.textContent = "Saving…";
    try {
      const enabled = this.select.value === "on";
      await api("/api/settings/reasoning", { method: "PUT", body: JSON.stringify({ enabled }) });
      this.status.textContent = "Saved — applies from the next message.";
    } catch (err) {
      this.status.textContent = `Failed to save: ${err.message}`;
    } finally {
      this.saveBtn.disabled = false;
    }
  }
}

const reasoningSection = document.getElementById("reasoning-section");
if (reasoningSection) new ReasoningSwitchForm(reasoningSection);
