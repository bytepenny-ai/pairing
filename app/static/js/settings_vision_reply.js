/* Admin settings > Models > Default models: what a reply to an image includes (/api/settings/vision-reply-context). Uses api from app.js. */
class VisionReplySetting {
  static URL = "/api/settings/vision-reply-context";

  constructor(root) {
    this.select = root.querySelector("#vision-reply-include");
    this.status = root.querySelector("#vision-reply-status");
    root.querySelector("#vision-reply-save-btn").addEventListener("click", () => this.save());
    this.load();
  }

  async load() {
    try {
      this.select.value = (await api(VisionReplySetting.URL)).include;
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  async save() {
    this.status.textContent = "Saving…";
    try {
      const saved = await api(VisionReplySetting.URL, { method: "PUT", body: JSON.stringify({ include: this.select.value }) });
      this.select.value = saved.include;
      this.status.textContent = "Saved";
    } catch (err) {
      this.status.textContent = `Not saved: ${err.message}`;
    }
  }
}

const visionReplyPanelEl = document.getElementById("vision-reply-panel");
PageViews.whenShown(visionReplyPanelEl, () => new VisionReplySetting(visionReplyPanelEl)); // on its page's first showing
