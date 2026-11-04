#!/bin/zsh
# scout_tick.sh: once-a-day scout tick (launchd com.cole.ambientizer-scout, 08:30 PT).
# Cole's yes via Chief, 2026-11-03: a 2-week trial ending 2026-11-17, seeded from his touchstones,
# one lead per tick, writing to data/scout/, stopping on its own when nothing new turns up.
# Instructions live in data/scout/PROMPT.md; memory lives in data/scout/SCRATCHPAD.md.
# Retires itself (bootout + plist renamed .retired) after END_DATE, after 3 dry ticks in a row, or
# when the scratchpad says stop: yes.

END_DATE=2026-11-17
DIR=/Users/colemonroe/Projects/Ambientizer
PLIST=$HOME/Library/LaunchAgents/com.cole.ambientizer-scout.plist
PAD=$DIR/data/scout/SCRATCHPAD.md
cd $DIR || exit 1

retire() {
  echo "$(date '+%F %T') RETIRE: $1"
  mv -f $PLIST $PLIST.retired 2>/dev/null
  launchctl bootout gui/$UID/com.cole.ambientizer-scout 2>/dev/null
  exit 0
}
status() { awk -v k="$1:" '$1==k {print $2; exit}' $PAD; }

[[ $(date +%F) > $END_DATE ]] && retire "trial ended $END_DATE"
[[ $(status stop) == yes ]] && retire "scratchpad says stop"
(( $(status dry_streak) >= 3 )) && retire "3 dry ticks in a row"

echo "$(date '+%F %T') tick start"
mkdir -p data/scout/ticks
# This run reads the open web, so it gets no outward tools (Chief, 11-04, on Cole's word).
ENABLE_CLAUDEAI_MCP_SERVERS=false perl -e 'alarm 1800; exec @ARGV' /opt/homebrew/bin/claude -p --model claude-opus-5-5 \
  --permission-mode bypassPermissions --disallowedTools='mcp__*,PushNotification,RemoteTrigger,Artifact,SendMessage' \
  "[scout-tick] Automation, not Cole. Today is $(date +%F). Follow data/scout/PROMPT.md exactly: one lead, findings, rewrite the scratchpad, write today's tick report."
echo "$(date '+%F %T') tick end (exit $?)"

git add data/scout && git commit -q -m "scout tick $(date +%F)" -- data/scout && git push -q 2>&1 | tail -1

# Check right away so a stop today doesn't wait for tomorrow's run.
[[ $(status stop) == yes ]] && retire "scratchpad says stop"
(( $(status dry_streak) >= 3 )) && retire "3 dry ticks in a row"
exit 0
