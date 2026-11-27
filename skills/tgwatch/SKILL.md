---
name: tgwatch
description: Turn this session into a live, two-way Telegram remote control using `telegram watch`. Automatically takes over from any previous watching session via software handoff, handles incoming text, photos, documents, and voice notes, and keeps listening until stopped or handed off. Use when the user invokes /tgwatch or asks for live continuous Telegram control.
argument-hint: "[optional initial task]"
allowed-tools: Bash(telegram:*)
---

The user wants to control this session live from Telegram via the `telegram` CLI (on PATH). Always reply in the same language the user writes in. Every message is automatically headed with host and project directory.

Initial task (if any): $ARGUMENTS

### 1. Start live watch (takeover)
1. If an initial task was given, work on it first and send the result via `telegram send`. Otherwise, send a short 1-line greeting (`telegram send "🟢 Live watch active."` in the user's language) so the user knows this session now has the floor.
2. Start `telegram watch` in the background (`background: true` / `run_in_background`).
   - Do **NOT** pass `--resume` on the initial start. A fresh `telegram watch` automatically claims the local watch lock and sends `SIGUSR1` + `[STOP]` to any previous watching session so two sessions never collide.

### 2. Handle watch output
When the background `telegram watch` completes:

- **Handoff / Stop (`exit code 10` or output starting with `[STOP]`):**
  Stop immediately. Another session took over or `telegram stop` was run.
  Do **NOT** restart `telegram watch` and do **NOT** send a Telegram message. Just mention briefly in the terminal that watch ended.

- **Explicit user stop (`/stop`, `stop`, `kapat`, or asking to end listening):**
  Run `telegram stop`, send a short `🛑 Watch stopped.` message in the user's language, and stop listening.

- **Incoming task / message:**
  - **Photos / screenshots** (`[file: ...jpg/png]`): inspect directly with your file-reading tool.
  - **Documents** (`[file: ...]`): read or inspect as needed.
  - **Voice / audio** (`[voice] [file: ...ogg]`): transcribe with any audio/STT tool or API available in this environment and act on what was said; if none is available, let the user know on Telegram.
  - Perform the requested work. For risky or irreversible steps (deploy, push, delete, migration), ask first with `telegram ask "..." -o Yes -o No`.
  - Send a concise reply via `telegram send` (or `telegram file <path> "caption"`).

### 3. Re-arm with `--resume`
Immediately after replying, start `telegram watch --resume` in the background.
- Always use `--resume` when re-arming. If another session took over while you were busy working, `--resume` detects the new owner, prints `[STOP]`, and exits with code `10` without stealing control back.
- Keep looping until you receive `[STOP]` (exit code `10`) or the user tells you to stop.
- If `telegram` exits with an unexpected error (not `10`), report it in the terminal and do not loop blindly.
