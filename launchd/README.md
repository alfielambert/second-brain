# Scheduling (macOS launchd)

Copy `com.secondbrain.dailysync.plist.template` to
`~/Library/LaunchAgents/com.secondbrain.dailysync.plist`, replace
`{{VAULT_ROOT}}`, `{{SECOND_BRAIN_BIN}}` (output of `which second-brain`),
`{{PATH}}`, and `{{HOME}}` with real values, then:

```
launchctl load ~/Library/LaunchAgents/com.secondbrain.dailysync.plist
```

On Linux, a systemd timer or plain cron entry running the same
`second-brain sync --connector ... && second-brain route` command achieves
the same thing - launchd is a macOS-specific packaging detail, not part of
the architecture.

Not included in v1: an independent watchdog process and a Telegram/chat
approval channel. Both are real, useful patterns from the private
reference implementation this project was extracted from, but neither is
part of the portable core - see docs/roadmap.md.
