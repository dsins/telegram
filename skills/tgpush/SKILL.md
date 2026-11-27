---
name: tgpush
description: Send task summaries, files, and interactive button approvals to Telegram without starting a background listener. Safe to run in parallel across multiple sessions. Use when the user invokes /tgpush or asks to be notified, updated, or asked for approval on Telegram.
argument-hint: "[task]"
allowed-tools: Bash(telegram:*)
---

The user is away from the terminal and wants updates or approvals for this task via the `telegram` CLI (on PATH). Always write messages in the same language the user used. Every message is automatically headed with host and project directory.

Task: $ARGUMENTS

Do **NOT** start `telegram watch`. This skill is strictly push + approval mode so multiple sessions can run in parallel without interfering with each other.

- **Results & milestones:** When the task finishes (or hits a blocker), run `telegram send "..."` with a short, scannable summary: what was done, the outcome, and anything remaining. On long tasks, send a one-line update only at real milestones. You can pipe output (`... | telegram send`); very long text is automatically sent as a `.txt` file.
- **Questions & approvals:** Any question you would normally ask in the terminal — and any risky or irreversible step (deploy, push, delete, migration, external send) — must go through:
  `telegram ask "Question?" -o Yes -o No` (omit `-o` for a free-text reply).
  Do not prompt in the terminal; nobody is watching it. `telegram ask` blocks until answered (default 30 min, `-t <seconds>`). If it times out with no answer, treat it as **No**: skip that step, report it as pending, and finish the rest.
- **Files:** For screenshots, reports, or logs worth seeing, use `telegram file <path> "caption"`.
- **On error:** If `telegram` itself fails, report the error in the terminal and do not execute any step that required approval.
