# Changelog

Notable changes in each pAIring release. Security fixes are marked **Security**. Full release notes and news:
https://bytepenny.com/rss/

## Unreleased

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
