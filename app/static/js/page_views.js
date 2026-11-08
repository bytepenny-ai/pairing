/**
 * Pages with inner pages (My/Admin settings: #tab-<name>, Cluster: #cluster-view-<name>) build every inner page
 * into one document and hide the rest. Their data loads only when an inner page is first shown, as the Stats page
 * does: `whenShown(el, fn)` runs `fn` once, the first time the inner page holding `el` is shown (at once if it is
 * shown now); `whileShown(el, fn)` tells `fn(true/false)` each time it is shown or hidden (pollers stop meanwhile).
 * settings.js (activateTab) and cluster.js (activateClusterView) call `changed()` after switching. Loaded first.
 */

class PageViews {
  static #pending = [];
  static #watchers = [];

  /** The inner page holding `el`; null when `el` is on every inner page (the page's header, for example). */
  static panelOf(el) {
    return el.closest('[id^="tab-"], [id^="cluster-view-"]');
  }

  static isShown(el) {
    const panel = PageViews.panelOf(el);
    return !panel || !panel.classList.contains("hidden");
  }

  static whenShown(el, fn) {
    if (!el) return;
    if (PageViews.isShown(el)) PageViews.#run(fn);
    else PageViews.#pending.push({ el, fn });
  }

  static whileShown(el, fn) {
    if (!el) return;
    const watcher = { el, fn, shown: PageViews.isShown(el) };
    PageViews.#watchers.push(watcher);
    PageViews.#run(() => fn(watcher.shown));
  }

  /** After an inner page is shown or hidden: first-time loads, then the watchers whose state changed. */
  static changed() {
    const ready = PageViews.#pending.filter((p) => PageViews.isShown(p.el));
    PageViews.#pending = PageViews.#pending.filter((p) => !ready.includes(p));
    for (const { fn } of ready) PageViews.#run(fn);
    for (const watcher of PageViews.#watchers) {
      const shown = PageViews.isShown(watcher.el);
      if (shown !== watcher.shown) {
        watcher.shown = shown;
        PageViews.#run(() => watcher.fn(shown));
      }
    }
  }

  /** One part failing (a sync throw or a rejected promise) never stops the others. */
  static #run(fn) {
    try {
      const result = fn();
      if (result && typeof result.catch === "function") result.catch((err) => console.error("Page part failed:", err));
    } catch (err) {
      console.error("Page part failed:", err);
    }
  }
}
