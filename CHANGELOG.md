# Changelog

Notable changes in each pAIring release. Security fixes are marked **Security**. Full release notes and news:
https://bytepenny.com/rss/

## Unreleased

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
