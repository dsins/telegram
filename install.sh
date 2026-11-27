#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
FORCE_CLAUDE=0
FORCE_OPENCODE=0

for arg in "$@"; do
  case "$arg" in
    --claude) FORCE_CLAUDE=1 ;;
    --opencode) FORCE_OPENCODE=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--claude] [--opencode]"
      echo "Installs the \`telegram\` CLI to ~/.local/bin and symlinks tgpush + tgwatch skills"
      echo "for any detected AI coding agent (Claude Code, OpenCode)."
      exit 0
      ;;
  esac
done

chmod +x "$DIR/telegram.py"

# 1. Install CLI -> ~/.local/bin/telegram
mkdir -p "$HOME/.local/bin"
ln -sfn "$DIR/telegram.py" "$HOME/.local/bin/telegram"

# Ensure ~/.local/bin is on PATH in shell rc files if missing
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  if [ -f "$rc" ] && ! grep -q '\.local/bin' "$rc"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
  fi
done

installed_agents=()

# 2. Claude Code (~/.claude/skills)
if [ "$FORCE_CLAUDE" -eq 1 ] || [ -d "$HOME/.claude" ]; then
  mkdir -p "$HOME/.claude/skills"
  rm -rf "$HOME/.claude/skills/tgpush" "$HOME/.claude/skills/tgwatch"
  ln -sfn "$DIR/skills/tgpush" "$HOME/.claude/skills/tgpush"
  ln -sfn "$DIR/skills/tgwatch" "$HOME/.claude/skills/tgwatch"
  # Clean up legacy skills replaced by tgpush & tgwatch
  rm -rf "$HOME/.claude/skills/tg" "$HOME/.claude/skills/notification"
  installed_agents+=("Claude Code (~/.claude/skills/{tgpush,tgwatch})")
fi

# 3. OpenCode (~/.config/opencode/skills & commands)
if [ "$FORCE_OPENCODE" -eq 1 ] || [ -d "$HOME/.config/opencode" ]; then
  mkdir -p "$HOME/.config/opencode/skills" "$HOME/.config/opencode/commands"
  rm -rf "$HOME/.config/opencode/skills/tgpush" "$HOME/.config/opencode/skills/tgwatch"
  ln -sfn "$DIR/skills/tgpush" "$HOME/.config/opencode/skills/tgpush"
  ln -sfn "$DIR/skills/tgwatch" "$HOME/.config/opencode/skills/tgwatch"
  ln -sfn "$DIR/commands/opencode/tgpush.md" "$HOME/.config/opencode/commands/tgpush.md"
  ln -sfn "$DIR/commands/opencode/tgwatch.md" "$HOME/.config/opencode/commands/tgwatch.md"
  # Clean up legacy skills & commands replaced by tgpush & tgwatch
  rm -rf "$HOME/.config/opencode/skills/tg" "$HOME/.config/opencode/skills/notification"
  rm -f "$HOME/.config/opencode/commands/tg.md" \
        "$HOME/.config/opencode/commands/telegram.md" \
        "$HOME/.config/opencode/commands/notification.md"
  installed_agents+=("OpenCode (~/.config/opencode/skills & /tgpush, /tgwatch)")
fi

echo "✅ Installed telegram CLI & skills:"
echo "  • CLI: ~/.local/bin/telegram -> $DIR/telegram.py"
if [ "${#installed_agents[@]}" -gt 0 ]; then
  for item in "${installed_agents[@]}"; do
    echo "  • $item"
  done
else
  echo "  • No agent directory detected (~/.claude or ~/.config/opencode)."
  echo "    Re-run with --claude or --opencode whenever you want the skills linked."
fi

if [ ! -f "$HOME/.config/telegram/config.json" ] && [ ! -f "$HOME/.config/ds/telegram.json" ]; then
  echo ""
  echo "👉 Next step (first time only):"
  echo "   telegram setup"
fi
