#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

chmod +x "$DIR/telegram.py"

# telegram CLI -> ~/.local/bin/telegram
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/telegram.py" "$HOME/.local/bin/telegram"

# Ensure ~/.local/bin is on PATH in ~/.bashrc if missing
if [ -f "$HOME/.bashrc" ] && ! grep -q '\.local/bin' "$HOME/.bashrc"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi

# Claude Code skills (/tg & /notification)
mkdir -p "$HOME/.claude/skills/tg" "$HOME/.claude/skills/notification"
cp "$DIR/skills/tg/SKILL.md" "$HOME/.claude/skills/tg/SKILL.md"
cp "$DIR/skills/notification/SKILL.md" "$HOME/.claude/skills/notification/SKILL.md"

echo "✅ Installed:"
echo "  • CLI:    ~/.local/bin/telegram -> $DIR/telegram.py"
echo "  • Skills: ~/.claude/skills/tg & ~/.claude/skills/notification"
echo ""
echo "👉 Next step (first time only):"
echo "   telegram setup"
