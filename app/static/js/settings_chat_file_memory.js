/* Admin settings > System > Chat > Files in a chat (/api/settings/chat-file-memory). Uses api from app.js. */
class ChatFileMemorySetting {
  static URL = "/api/settings/chat-file-memory";

  constructor(root) {
    this.percent = root.querySelector("#chat-file-whole-percent");
    this.imageFollowUp = root.querySelector("#chat-file-image-follow-up");
    this.related = root.querySelector("#chat-file-image-related");
    this.unrelated = root.querySelector("#chat-file-image-unrelated");
    this.status = root.querySelector("#chat-file-memory-status");
    root.querySelector("#chat-file-memory-save-btn").addEventListener("click", () => this.save());
    this.load();
  }

  show(setting) {
    this.percent.value = setting.whole_file_percent;
    this.imageFollowUp.value = setting.image_follow_up;
    this.related.value = setting.related_above;
    this.unrelated.value = setting.unrelated_below;
  }

  async load() {
    try {
      this.show(await api(ChatFileMemorySetting.URL));
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  async save() {
    this.status.textContent = "Saving…";
    const body = {
      whole_file_percent: Number(this.percent.value),
      image_follow_up: this.imageFollowUp.value,
      related_above: Number(this.related.value),
      unrelated_below: Number(this.unrelated.value),
    };
    try {
      this.show(await api(ChatFileMemorySetting.URL, { method: "PUT", body: JSON.stringify(body) }));
      this.status.textContent = "Saved";
    } catch (err) {
      this.status.textContent = `Not saved: ${err.message}`;
    }
  }
}

const chatFileMemoryPanelEl = document.getElementById("chat-file-memory-panel");
if (chatFileMemoryPanelEl) PageViews.whenShown(chatFileMemoryPanelEl, () => new ChatFileMemorySetting(chatFileMemoryPanelEl));
