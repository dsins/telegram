# Telegram 📲 Pocket Remote Control for Shell & AI Coding Agents

Walk away from your keyboard without walking away from your work.

`telegram` is a **single-file, zero-dependency Python 3 CLI** and **2-skill pack (`tgpush` + `tgwatch`)** that turns your own private Telegram bot into a live remote control for **OpenCode**, **Claude Code**, or any terminal script.

- **Zero dependencies:** Pure Python 3 standard library. No `pip install`, no Node runtime, no cloud relay, no daemon.
- **`watch` is the default:** Run `telegram` and it starts listening immediately — cursor saved, photos/docs/voice downloaded automatically.
- **Bulletproof session handoff:** Open a new AI session and start `tgwatch` — it takes over in software, politely tells the old agent `[STOP]` so it never restarts, and cleans up the old watcher automatically.
- **Multi-machine friendly:** Updates are never wiped on Telegram's side (Telegram keeps them 24h), and every message arrives headed with **`host · folder`**.

---

## 🧠 Why I Built It This Way (The Story)

I run multiple AI coding sessions across servers and projects, and I don't want to stay glued to a terminal waiting for builds, deploys, or long refactors. I wanted to grab a coffee, take a walk, and still nudge my agent, inspect a screenshot, or tap **Yes / No** on a deploy from my phone.

When you actually use a Telegram bridge every day with AI agents, you hit four real-world walls fast. Every design decision in this repo comes directly from slamming into those walls:

1. **Why one skill wasn't enough (`tgpush` vs `tgwatch`)**
   At first, I crammed everything into a single `/tg` skill — "notify me when done" *and* "keep listening forever." Bad idea. Sometimes the agent started an infinite background listener when I only wanted a one-off ping; other times it stopped listening when I was out the door.
   Splitting into two sharp skills fixed it overnight:
   - **`/tgpush`** = fire-and-forget updates, files, and button approvals. No background listener, so **10 sessions can push in parallel** without ever stepping on each other.
   - **`/tgwatch`** = live, two-way remote control. Exactly **one** session holds the mic at a time.
   - And I dropped the separate cron-watcher skill I used to maintain. Why carry 80 lines of prompt template when `telegram send` is already a one-liner in any crontab?

2. **Why `watch` is the default command**
   Typing `telegram wait --cursor ... --download ...` gets old on day one. Live listening is the heart of the tool, so bare `telegram` (or `telegram watch`) just works out of the box with sensible defaults for cursor tracking and media downloads.

3. **Why session handoff MUST be enforced in software (not left to the AI)**
   Picture this: Session A is happily watching Telegram. You open Session B in another project and start `/tgwatch`.
   - If you do nothing -> both sessions read the same message and fight over it.
   - If you ask the AI to "remember to stop the other session" -> good luck, LLMs forget or don't even know Session A exists.
   - If you just `kill` Session A's watcher -> Agent A sees an unexpected crash, thinks *"oh, network blip!"*, and **restarts `telegram watch`** — kicking off an endless tug-of-war between two AI agents!
   - And you can't just send `/stop` over Telegram either, because **Telegram bots never receive their own messages in `getUpdates`**.

   So `telegram watch` handles handoff deterministically in ~40 lines of standard Python:

   ```text
   Session B runs `telegram watch`
     ├─ 1. Atomically claims ~/.local/state/telegram/active.json
     ├─ 2. Sends SIGUSR1 to Session A's watcher PID (SIGTERM fallback if hung)
     └─ 3. Session A's watcher wakes in <1ms, prints:
             [STOP] Telegram watch handed off to another session (host · project-b).
                    Stop listening and do NOT restart telegram watch.
           and exits cleanly with exit code 10.
   ```

4. **What if Session A was busy working when Session B took over?**
   Think about that edge case: Session A received a message, exited `watch`, and spent 3 minutes refactoring code. Meanwhile, you switched to Session B and started `/tgwatch`. When Session A finishes and tries to re-arm, it runs **`telegram watch --resume`**.
   `--resume` checks `active.json`, sees Session B now owns the floor, prints `[STOP]` (exit code `10`), and quietly steps aside — **never stealing control back**.

Simple. No daemon. No ports. No agent guesswork.

---

## ⚡ 60-Second Quickstart

### 1. Clone & Install

```bash
git clone https://github.com/dsins/telegram.git
cd telegram
./install.sh
```

What `install.sh` does:
- Symlinks `telegram.py` to `~/.local/bin/telegram` (and adds it to your `PATH` if needed).
- Auto-detects **Claude Code** (`~/.claude`) and/or **OpenCode** (`~/.config/opencode`) and symlinks the `tgpush` + `tgwatch` skills (and `/tgpush`, `/tgwatch` slash commands for OpenCode). Because they're symlinks, `git pull` keeps everything updated automatically.

### 2. Create Your Bot & Link Your Chat

1. Open **[@BotFather](https://t.me/BotFather)** on Telegram, send `/newbot`, and copy the HTTP API token.
2. Run:
   ```bash
   telegram setup
   ```
3. Paste your token, then send any message (`hi`) to your new bot from your phone.
4. Done! Credentials are stored locally in `~/.config/telegram/config.json` (`0600` permissions, outside the repo) and you'll get a **"✅ Connected"** ping on your phone.

> **Adding another server or laptop?** Copy `~/.config/telegram/config.json` over, or just run `telegram setup <TOKEN> <CHAT_ID>`.

---

## 🤖 Using the AI Agent Skills

| Skill / Command | Best for | Runs `watch`? | Parallel sessions? |
|---|---|---|---|
| **`/tgpush`** | *"Run tests, fix errors, ask me before pushing, ping me when done."* | No | Yes (unlimited) |
| **`/tgwatch`** | *"Heading out — keep listening so I can send tasks, screenshots, and voice notes from my phone."* | Yes (singleton) | Takes over cleanly |

### `/tgpush` — Fire, Report & Ask
```text
/tgpush run the full test suite, fix any failures, and ask me on Telegram before git push
```
- Sends a crisp summary when finished (or at major milestones).
- Risky steps (`deploy`, `push`, `delete`, `migration`) pop up as **Yes / No inline buttons** on your phone.
- Safe to trigger across as many parallel terminals/sessions as you want.

### `/tgwatch` — Live Two-Way Remote Control
```text
/tgwatch
```
- Announces itself on Telegram and starts `telegram watch` in the background.
- Send text, screenshots, files, or voice notes from your phone — your agent inspects them, executes, replies, and immediately re-arms with `telegram watch --resume`.
- Open `/tgwatch` in a *different* session anytime: the old session gets `[STOP]` automatically and bows out cleanly.
- Send `/stop` on Telegram (or run `telegram stop` in any terminal) whenever you want to hang up.

---

## 💻 CLI Cheat Sheet

Works great on its own in shell scripts, CI hooks, or cron jobs too:

```bash
# Watch for incoming messages (default command — bare `telegram` does the same!)
telegram
telegram watch --json                      # structured JSON output
telegram watch --resume                    # re-arm only if this session still owns the lock
telegram stop                              # cleanly stop the active local watcher

# Send text (or pipe command output; very long text becomes a .txt attachment)
telegram send "Build is green 🚀"
pytest 2>&1 | tail -n 30 | telegram send

# Send any file (report, screenshot, log)
telegram file report.pdf "Weekly summary"

# Ask with inline buttons (blocks until tapped or replied, prints the answer)
ANSWER=$(telegram ask "Deploy to production?" -o "Ship it" -o "Hold")
echo "Chosen: $ANSWER"

# Ask for a free-text reply (omit -o)
telegram ask "Which branch should I deploy?"

# Read your messages from the last 24h
telegram list
```

### Bonus: Cron Alerts in One Line (No Extra Skill Needed)

```cron
# Ping Telegram if your site stops returning HTTP 200
*/5 * * * * curl -fsS https://example.com >/dev/null || TELEGRAM_LABEL="monitor · prod" $HOME/.local/bin/telegram send "🚨 example.com is down!"
```

---

## ⚙️ Environment Variables (All Optional)

| Variable | Description | Default |
|---|---|---|
| `TELEGRAM_CONFIG` | Path to config JSON (also checks legacy `DS_TELEGRAM_CONFIG`) | `~/.config/telegram/config.json` |
| `TELEGRAM_BOT_TOKEN` | Bot token via env (skips config file) | — |
| `TELEGRAM_CHAT_ID` | Linked private chat ID via env | — |
| `TELEGRAM_LABEL` | Bold header on the first line of every message | `<hostname> · <folder>` |
| `TELEGRAM_STATE_DIR` | Directory for `cursor.json`, `active.json`, and `inbox/` | `~/.local/state/telegram` |
| `TELEGRAM_INBOX_TTL` | Auto-delete managed inbox files older than N seconds (`0` disables) | `86400` (24h) |
| `TELEGRAM_OWNER` | Custom owner ID for `--resume` lock checks | `OPENCODE_SESSION_ID` / `CLAUDE_SESSION_ID` / `cwd` |

---

## 🧹 Performance & Zero Data Bloat

Built to run 24/7 on tiny VPS instances without leaking memory or filling disks:

- **Tiny footprint:** Idles on `select()` (~0% CPU, ~12–15 MB RAM, one Python process) and keeps only two tiny JSON state files (`cursor.json` and `active.json`, <1 KB total).
- **No old-message replay or context bloat:** `cursor.json` tracks `last_update_id`, so old chat history is never re-processed, downloaded, or fed back into your AI agent. On the network side, updates stay unconfirmed so multiple devices can share one bot; Telegram automatically expires them after 24 hours (capped at the latest 100 updates, a few KB of JSON).
- **Automatic inbox pruning:** Incoming photos, voice notes, and documents saved in the default `~/.local/state/telegram/inbox/` folder are automatically cleaned up after **24 hours** whenever `telegram watch` starts (custom `--download` directories are never touched).

---

## 🔒 Privacy & Security

- **Direct to Telegram:** Talks straight to `api.telegram.org` — no third-party relay server in the middle.
- **Locked to your chat:** Only messages and button taps from your own linked `chat_id` are accepted; anyone else messaging your bot is ignored.
- **Local secrets only:** Token and chat ID live in `~/.config/telegram/config.json` with `0600` permissions.

---

## 📁 Repo Layout

```text
.
├── telegram.py                     # Zero-dependency Python 3 CLI (default: watch)
├── install.sh                      # Installs CLI + symlinks skills for Claude Code & OpenCode
├── skills/
│   ├── tgpush/SKILL.md             # Push updates, files & inline button approvals
│   └── tgwatch/SKILL.md            # Live two-way watch with automatic session handoff
├── commands/opencode/
│   ├── tgpush.md                   # /tgpush slash command for OpenCode
│   └── tgwatch.md                  # /tgwatch slash command for OpenCode
└── LICENSE                         # MIT
```
