---
name: tg
description: Work while the user is away and keep them posted on Telegram - send results, ask for approvals and answers there. Use when the user types /tg or asks to be notified, updated or asked over Telegram ("telegramdan bildir", "haber ver", "onay al").
argument-hint: "[görev]"
allowed-tools: Bash(telegram:*)
---

The user is away from the terminal and follows this session on Telegram through the `telegram` CLI (on PATH). Write to them in Turkish. Every message is headed with host and project automatically.

Task: $ARGUMENTS

With no task given, run `telegram list` and take their latest messages there as the task.

- **Results:** when the task is done or you have to stop, `telegram send` a short summary: what was done, the outcome, anything left or blocking. On a long task also send a one-line update at real milestones, not every step. Output can be piped (`... | telegram send`); very long text arrives as a .txt file.
- **Questions and approvals:** anything you would ask in the terminal, and any risky or irreversible step (deploy, push, delete, migration, sending something to other people), goes through `telegram ask "..." -o Evet -o Hayır` (leave out `-o` for a free-text answer). It prints the answer and blocks until they reply (default 30 min, `-t <seconds>`), so start it with `run_in_background` and wait for it to exit before doing what you asked about. Do not use AskUserQuestion: nobody is at the terminal. No answer means no: skip that step, report it as pending and finish the rest.
- **Files** worth seeing (screenshot, report, log): `telegram file <path> "caption"`.
- **Live continuous mode (`telegram wait`):** When the user wants a continuous two-way link ("yazdıkça devam et", "dışarı çıkıyorum", "dinlemeye devam et"):
  1. Start `telegram wait --cursor ~/.local/state/ds-telegram/cursor-${OPENCODE_SESSION_ID:-default}.json --download /tmp/opencode/tg-inbox` in the background (`background: true`).
  2. When it returns incoming messages (including downloaded screenshots/files), do the requested work and reply via `telegram send` (or `telegram file`).
  3. Immediately re-arm `telegram wait` in the background using the SAME `--cursor` file so messages sent while you were busy are never missed.
  4. Never stop listening unless the user explicitly writes `/stop`, `kapat`, or `dinlemeyi durdur`.
- If `telegram` itself fails, say so in the terminal and do not take the step you needed approval for.
