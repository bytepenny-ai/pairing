/* While the engine reads a long prompt (a long file on a CPU can take many minutes before the first word), the reply's
   waiting label shows how far it got and an estimate of the time left, from how fast the percentage has been moving:
   "Reading… 35% · about 12 min left". Fed by the reply stream's "read_progress" events (0 to 1,
   reply_side_events.py); renderReplyBody (chat.js) asks for the label. */
class ReadProgress {
  /* Records a new fraction for `bubble`; the first one starts the clock for the estimate. */
  static set(bubble, fraction) {
    const now = Date.now();
    if (!bubble._readStart) bubble._readStart = { at: now, fraction };
    bubble._readProgress = { at: now, fraction };
  }

  /* The waiting label, or null before any progress arrived. */
  static label(bubble) {
    const current = bubble._readProgress;
    if (!current) return null;
    const percent = Math.floor(current.fraction * 100);
    const start = bubble._readStart;
    const done = current.fraction - start.fraction;
    if (done <= 0 || current.at <= start.at) return `Reading… ${percent}%`;
    const secondsLeft = ((current.at - start.at) / 1000 / done) * (1 - current.fraction);
    return `Reading… ${percent}% · ${ReadProgress.left(secondsLeft)}`;
  }

  static left(seconds) {
    if (seconds < 90) return "under 2 min left";
    if (seconds >= 3600) return "over an hour left";
    return `about ${Math.round(seconds / 60)} min left`;
  }
}
