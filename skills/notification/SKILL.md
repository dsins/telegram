---
name: notification
description: Set up a watch that keeps running after Claude Code is closed - a cron job that checks something on a schedule (a domain drops or expires, a site goes down or changes, a price or stock appears, a cert expires, a job or file finishes) and messages the user on Telegram itself. Also lists and removes these watches. Use when the user types /notification or asks to be told later when something happens ("... olunca haber ver", "takip et", "izle", "bildirim kur", "düşünce yaz").
argument-hint: "[neyi takip edeyim | liste | sil <ad>]"
---

Request: $ARGUMENTS

A watch is a small bash script in a user crontab entry. The script does its check and calls `telegram send` itself, so it does not depend on Claude Code or any open terminal. It only needs this computer to be on: if the machine is asleep, that run is skipped and the next run catches up. Explain this to the user in one or two Turkish sentences when you set one up.

## No request, `liste`, or `sil <ad>`

- List: `crontab -l | grep 'ds-watch:'`. For each watch show its name, schedule and what it checks (the header of its `check.sh`), plus the last lines of its `log`.
- Remove: `crontab -l | grep -v "# ds-watch:<ad>$" | crontab -`. Leave the directory in place and say where it is.

## Setting one up

1. **Understand what is watched.** Work out the exact signal: which URL or API, which value, and what counts as "it happened". Probe it once by hand. Use an official API or endpoint where one exists (e.g. RDAP rather than scraping), and pick the slowest schedule that still serves the need. Respect the target's rate limits, and offset the minute rather than using `:00`. If the request is unclear, ask in the terminal before building anything.
2. **Create the watch:**
   - Directory: `~/.local/share/ds-watch/<ad>/`, where `<ad>` is a short kebab-case name. It holds `check.sh`, its data, state files and `log`.
   - Start from the template below. Write the user-facing messages in Turkish. Each message begins with 🎯 (the event happened), ⚠️ (the check itself is failing) or ✅ (the watch finished and switched itself off).
3. **The script must:**
   - Report each event once. Remember what was already sent in a state file, so the user gets a message when something changes, not on every run.
   - Warn once if the check keeps failing (network, changed page format, 429). The template does this after 3 failed runs in a row.
   - Switch itself off when nothing is left to wait for: every item happened, or a deadline passed. It removes its own crontab line and sends a ✅ message.
   - Use absolute paths only. Cron's PATH is `/usr/bin:/bin` and does not include `~/.local/bin`, so call `$HOME/.local/bin/telegram`. In the crontab line a literal `%` must be written as `\%`.
4. **Test it in a cron-like environment before installing:**
   - Run `env -i HOME="$HOME" PATH=/usr/bin:/bin /bin/bash ~/.local/share/ds-watch/<ad>/check.sh`. It must exit 0 and must not send a false event.
   - Then send the setup notice the same way. This also proves Telegram works from cron: `env -i HOME="$HOME" PATH=/usr/bin:/bin TELEGRAM_LABEL="ds-watch · <ad>" "$HOME/.local/bin/telegram" send "🔔 Takip kuruldu: ..."`.
5. **Install it without touching other crontab lines:**
   `(crontab -l 2>/dev/null | grep -v "# ds-watch:<ad>$"; echo "<dk> <saat> * * * $HOME/.local/share/ds-watch/<ad>/check.sh >> $HOME/.local/share/ds-watch/<ad>/log 2>&1 # ds-watch:<ad>") | crontab -`
   Expand `$HOME` in the line, then check the result with `crontab -l`.
6. **Tell the user in Turkish:**
   - what is checked, how often, and what message will arrive;
   - that it keeps working with Claude closed, as long as the computer is on;
   - how to stop it: `/notification sil <ad>`, or delete the `ds-watch:<ad>` line with `crontab -e`;
   - where the log is.

If the event is time-critical and this machine may be off or asleep, say so. Offer to install the same watch on one of their servers from `~/.ssh/config`. That server needs the `telegram` CLI and its config; copy the config only after the user agrees, since it holds the bot token.

## Template

```bash
#!/bin/bash
# ds-watch <ad>: <one line: what is checked and what counts as the event>
set -u
NAME=<ad>
DIR="$HOME/.local/share/ds-watch/$NAME"
TG="$HOME/.local/bin/telegram"
export TELEGRAM_LABEL="ds-watch · $NAME"
cd "$DIR" || exit 1
touch reported fails

stop_watch() {  # remove our crontab line and say goodbye
  crontab -l 2>/dev/null | grep -v "# ds-watch:$NAME\$" | crontab -
  "$TG" send "✅ $1"
}

ok=0
# --- the check: set ok=1 when the target answered at all, report events once ---
# item=...; result=$(curl -s -m 20 ...) && ok=1
# if <event for $item> && ! grep -qx "$item" reported; then
#   echo "$item" >> reported
#   "$TG" send "🎯 ..."
# fi
# ---

if [ "$ok" = 1 ]; then
  : > fails
else
  echo x >> fails
  [ "$(wc -l < fails)" -eq 3 ] && "$TG" send "⚠️ $NAME: kontrol 3 kez üst üste başarısız oldu (log: $DIR/log). Düzelene kadar sessiz kalacağım."
fi

# when nothing is left to wait for:
# [ <all done> ] && stop_watch "$NAME: hepsi gerçekleşti, takip kapatıldı."
exit 0
```
