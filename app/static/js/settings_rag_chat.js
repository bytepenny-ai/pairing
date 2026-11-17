/* Admin settings > Inference > RAG: Knowledge in chats (app/templates/_rag_chat.html, /api/settings/rag-chat). Uses api from app.js. */
class RagChatSetting {
  static URL = "/api/settings/rag-chat";

  constructor(root) {
    this.root = root;
    this.similarity = root.querySelector("#rag-min-similarity");
    this.checkSources = root.querySelector("#rag-check-sources");
    this.sourceSimilarity = root.querySelector("#rag-source-min-similarity");
    this.checkSources.addEventListener("change", () => this.sync());
    this.status = root.querySelector("#rag-chat-status");
    root.querySelector("#rag-chat-save-btn").addEventListener("click", () => this.save());
    this.load();
  }

  render(setting) {
    this.similarity.value = setting.min_similarity;
    const choice = setting.keep_excerpts ? "keep" : "drop";
    this.root.querySelector(`input[name="rag-keep-excerpts"][value="${choice}"]`).checked = true;
    this.checkSources.checked = setting.check_sources;
    this.sourceSimilarity.value = setting.source_min_similarity;
    this.sync();
  }

  /* The answer cutoff matters only while the check is on. */
  sync() {
    this.sourceSimilarity.disabled = !this.checkSources.checked;
    this.sourceSimilarity.classList.toggle("opacity-50", !this.checkSources.checked);
  }

  async load() {
    try {
      this.render(await api(RagChatSetting.URL));
    } catch (err) {
      this.status.textContent = `Could not load: ${err.message}`;
    }
  }

  async save() {
    this.status.textContent = "Saving…";
    try {
      const keep = this.root.querySelector('input[name="rag-keep-excerpts"]:checked')?.value !== "drop";
      const body = JSON.stringify({
        min_similarity: Number(this.similarity.value),
        keep_excerpts: keep,
        check_sources: this.checkSources.checked,
        source_min_similarity: Number(this.sourceSimilarity.value),
      });
      this.render(await api(RagChatSetting.URL, { method: "PUT", body }));
      this.status.textContent = "Saved.";
    } catch (err) {
      this.status.textContent = `Failed to save: ${err.message}`;
    }
  }
}

const ragChatPanelEl = document.getElementById("rag-chat-panel");
PageViews.whenShown(ragChatPanelEl, () => new RagChatSetting(ragChatPanelEl)); // on its page's first showing (page_views.js)
