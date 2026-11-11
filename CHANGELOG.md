# Changelog

Notable changes in each pAIring release. Security fixes are marked **Security**. Full release notes and news:
https://bytepenny.com/rss/

## 2.1.3 (2026-11-11)

- Every log line starts with the date and time (`data/logs/app.log` and each instance's log), in the same format as Matricxon; the start-up database migration no longer swaps in a format without one.
- Admin settings > Models > Default models: "Replies to an image include": nothing (the default: just the message and the image), notes only, or notes and skills. Leaving them out makes image replies much faster on a CPU; text replies always include them.
- Chat attachments: after attaching, the message box fills in `/describe` (an image), `/summarize` (documents) or both for a mix, so a file can be sent without typing; add your own words after the command if you like. Files a model can't read (no vision model, a scanned PDF, an empty or damaged file) are refused when picked, with the reason.
- Admin settings > Models > Default models: a default forecasting model, preselected on the Forecast page.
- The Forecast page reads messy files: dates (any common format), newest-first rows, gaps, thousands separators and decimal commas, quoted cells, report lines above the table and older Excel exports. It refuses Excel workbooks, PDFs and pictures with a plain reason, and shows "About this forecast": time step, the dates covered, direction, likely range and any repeating pattern.
- Matricxon's wider CPU instructions setting is on by default for a new local Matricxon.
- Forecast page (sidebar, every user): paste numbers or upload a CSV and get the next values with a chart of the likely range, a table and a CSV download. Runs Google's TimesFM 2.5 on Matricxon; admins install it under Admin settings > Models > Forecasting models. Big files are read in the browser with a progress bar and Cancel (never uploaded); long forecasts keep the connection alive with no time limit by default. Max file size and time limit are admin settings shared by every server of a ring. Needs the matching Matricxon.

## 2.1.2 (2026-11-08)

- Memory pinning (Admin settings > Inference > Memory pinning): keep chosen models loaded on each Matricxon server. A square memory grid shows every server's RAM and GPU VRAM (a whole cluster at once), with moving dots for loads and unloads; pins are set per server or on every server that has the model, and chats prefer a server that has the model pinned (a chat still returns to the server holding its conversation, and busy servers still share the load). Each pin can choose RAM, GPU VRAM or auto. Uninstalling a model in a cluster removes its pin and unloads it on every node, and names any node that could not be cleaned. Needs the matching Matricxon.
- The cluster map shows "pAIring (ring mode)" when several pAIring servers share the database, with each server's name, IP and status in its panel.
- No limit of 120 remote servers per engine any more: a Matricxon cluster can have hundreds of nodes. A remote image server in a server ring must be an address every server reaches (not localhost).
- With more than one pAIring server on the database, the image engine runs only in remote mode, one image server every pAIring uses; in local mode image generation is off on every server (the Images Gen link shows Off) and local image engines are stopped, not uninstalled.
- Admin settings: a new Inference group holds Engine (was Inference engines), MCP servers and RAG (was under System).
- A server run by systemd restarts itself after an update when its user may run `sudo systemctl restart` (servers set up by `scripts/bootstrap_server.sh`), instead of asking for a manual restart.
- Update all also restarts a server that was updated without a restart (a pull or commit by hand), instead of calling it up to date; the version check names it.
- `scripts/start.sh` refuses to run as root with a clear message naming the user to start it as (`PAIRING_ALLOW_ROOT=1` for containers).
- The repository now ships its `.gitignore`: a server's clone no longer lists `.env`, caches and data as new files.
- Cluster > Servers: the last "Update all" box can be dismissed once it has ended.
- Cluster > Servers: removing an offline server also removes its offline instances; a running server's Remove is greyed out and says why. An ended "Update all" can be dismissed.
- Cluster > Servers shows each server's IP addresses under its name.
- With several local instances, saving from a browser on another machine no longer fails now and then with "Request blocked ... (CSRF check)".
- Local instances are set per server: a server sharing the database no longer runs another server's count (a new one starts with 1).
- With several local instances, a page load sent to one still starting is retried on another instead of failing with an error 500.
- A fresh install no longer fails at "Setting up the database" (No module named 'greenlet'): SQLAlchemy 2.1+ needs `sqlalchemy[asyncio]`.
- New server setup in two parts: `scripts/bootstrap_server.sh` once as root, then `scripts/setup_server.sh` as the pairing user, for a first pAIring or one joining existing pAIring servers (shared MySQL, SECRET_KEY, shared folders and Matricxon checked before install), with a checklist.
- The image engine shows "loading the model…" while it starts, and image requests wait for it instead of failing.
- A saved image model that was moved or deleted no longer shows as a stale entry on the engine page.
- Re-adding a model that is already listed points to its row instead of failing.
- **Security:** vulnerability reporting policy (SECURITY.md), CodeQL code scanning and Dependabot updates.
- Updated dependencies, including FastAPI 0.162.

## 2.1.1 (2026-11-03)

- Fixes after 2.1.

## 2.1 (2026-11-03)

- Skills: task instructions picked per chat or set for a whole channel, with 239 ready-made ones.
- Rolling updates: every pAIring server and Matricxon node updates in one step, from your own repository if you have one.
- Each reply shows its speed (tokens per second, time to first token). Chats export to Markdown.
- Daily usage limits per user. Files added to the knowledge folder are picked up without a restart.
- Matricxon API keys, set on one server or every cluster node, and the new sampling options.
- A new visual workflow design. Cluster mode fixes, including switching the engine while cluster mode is on.
- A Reasoning option on chats with Qwen 3.5 and Gemma 4.
- **Security:** CSRF protection.

## 2.0 (2026-10-20)

- Cloud connectors: Cloudflare Workers AI, DigitalOcean, OpenRouter, Gemini, Groq, NVIDIA NIM, Cohere and RunPod.
- New Matricxon engine settings. Design and session fixes, and fixes to the on-disk cache.

## 1.5 (2026-10-11)

- Cluster mode (BETA) for the Matricxon engine, managed from a live node map.
- Channel cache fixes, a channel reset for admins, and image generation and image-to-image fixes.

## 1.2 (2026-10-05)

- Tools through MCP. Sharing chat messages with channels. A chat cache panel in Settings.
- Math formulas in replies. Connectors for cloud GPUs. GPU and UI fixes.

## 1.0 (2026-09-22)

- First public release, under AGPL-3.0.
