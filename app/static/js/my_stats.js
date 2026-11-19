/* My stats page (my_stats.html): loads GET /api/my-stats and fills the cards, the per-day bars and the model list.
   Every value goes in with textContent, never as HTML. */

class MyStatsPage {
  constructor() {
    this.statusEl = document.getElementById("my-stats-status");
  }

  async load() {
    try {
      this.render(await api("/api/my-stats"));
      this.statusEl.classList.add("hidden");
    } catch (error) {
      this.statusEl.textContent = `Couldn't load your stats: ${error.message}`;
    }
  }

  render(stats) {
    this.today(stats.usage_today);
    this.bars(stats.activity);
    this.cards("my-stats-total-cards", [
      ["Chats", this.num(stats.totals.chats)],
      ["Messages sent", this.num(stats.totals.messages_sent)],
      ["Replies to you", this.num(stats.totals.replies)],
      ["In channels", this.num(stats.totals.channel_messages), "messages you sent"],
      ["Files attached", this.num(stats.totals.attachments)],
      ["Failed replies", this.num(stats.totals.failed_replies)],
    ]);
    const s = stats.speed;
    this.cards("my-stats-speed-cards", [
      ["Replies", this.num(s.replies)],
      ["Tokens written", this.num(s.output_tokens), "by the model"],
      ["Tokens read", this.num(s.prompt_tokens), "your prompts and context"],
      ["First word after", this.seconds(s.avg_first_token_ms), "on average"],
      ["Whole reply", this.seconds(s.avg_total_ms), "on average"],
      ["Speed", s.avg_tokens_per_second == null ? "—" : `${s.avg_tokens_per_second} tok/s`, "on average"],
    ]);
    this.models(stats.models);
    const lib = stats.library;
    this.cards("my-stats-library-cards", [
      ["Documents", this.num(lib.documents), `${this.bytes(lib.document_bytes)} · ${this.num(lib.document_chunks)} passages`],
      ["Folders", this.num(lib.folders)],
      ["Notes", this.num(lib.notes)],
      ["Skills", this.num(lib.skills), "written by you"],
      ["Images", this.num(lib.images), lib.failed_images ? `${this.num(lib.failed_images)} failed` : "generated"],
    ]);
    if (stats.member_since) {
      document.getElementById("my-stats-since").textContent =
        `Member since ${new Date(stats.member_since).toLocaleDateString()}.`;
    }
    for (const id of ["today", "activity", "totals", "speed", "library"]) this.show(`my-stats-${id}`);
  }

  today(usage) {
    const limit = (used, max) => (usage.exempt || !max ? this.num(used) : `${this.num(used)} / ${this.num(max)}`);
    this.cards("my-stats-today-cards", [
      ["AI replies", limit(usage.replies_used, usage.replies_limit)],
      ["Tokens written", limit(usage.tokens_used, usage.tokens_limit)],
    ]);
    document.getElementById("my-stats-limits-note").textContent = usage.exempt
      ? "Admins have no daily limits."
      : usage.replies_limit || usage.tokens_limit
        ? "Used out of your daily limit. It counts the last 24 hours, so it frees up gradually."
        : "No daily limits are set for you.";
  }

  bars(days) {
    const box = document.getElementById("my-stats-bars");
    const max = Math.max(1, ...days.map((d) => d.messages));
    box.replaceChildren(
      ...days.map((d) => {
        const bar = document.createElement("div");
        bar.className = "flex-1 rounded-t-sm " + (d.messages ? "bg-brand-500/80 hover:bg-brand-500" : "bg-slate-800");
        bar.style.height = d.messages ? `${Math.max(4, (d.messages / max) * 100)}%` : "2px";
        bar.title = `${this.day(d.day)}: ${d.messages} message${d.messages === 1 ? "" : "s"}`;
        return bar;
      }),
    );
    if (days.length) {
      document.getElementById("my-stats-bars-from").textContent = this.day(days[0].day);
      document.getElementById("my-stats-bars-to").textContent = this.day(days[days.length - 1].day);
    }
  }

  models(models) {
    if (!models.length) return;
    const list = document.getElementById("my-stats-model-list");
    const max = models[0].count;
    list.replaceChildren(
      ...models.slice(0, 8).map((m) => {
        const row = document.createElement("div");
        row.className = "space-y-1";
        const head = document.createElement("div");
        head.className = "flex justify-between gap-3 text-xs";
        const name = document.createElement("span");
        name.className = "truncate font-mono text-slate-300";
        name.textContent = m.key;
        const count = document.createElement("span");
        count.className = "shrink-0 text-slate-500";
        count.textContent = `${this.num(m.count)} chat${m.count === 1 ? "" : "s"}`;
        head.append(name, count);
        const track = document.createElement("div");
        track.className = "h-1.5 rounded-full bg-slate-800";
        const fill = document.createElement("div");
        fill.className = "h-full rounded-full bg-brand-500/80";
        fill.style.width = `${(m.count / max) * 100}%`;
        track.appendChild(fill);
        row.append(head, track);
        return row;
      }),
    );
    this.show("my-stats-models");
  }

  cards(id, items) {
    document.getElementById(id).replaceChildren(
      ...items.map(([label, value, hint]) => {
        const card = document.createElement("div");
        card.className = "rounded-lg bg-slate-900 border border-slate-800 px-4 py-3";
        const l = document.createElement("p");
        l.className = "text-xs text-slate-500";
        l.textContent = label;
        const v = document.createElement("p");
        v.className = "mt-1 text-lg font-semibold text-slate-100";
        v.textContent = value;
        card.append(l, v);
        if (hint) {
          const h = document.createElement("p");
          h.className = "text-[11px] text-slate-500";
          h.textContent = hint;
          card.appendChild(h);
        }
        return card;
      }),
    );
  }

  show(id) {
    document.getElementById(id).classList.remove("hidden");
  }

  num(n) {
    return Number(n || 0).toLocaleString();
  }

  seconds(ms) {
    return ms == null ? "—" : `${(ms / 1000).toFixed(1)} s`;
  }

  bytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  day(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
}

new MyStatsPage().load();
