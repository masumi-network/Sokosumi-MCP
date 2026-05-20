---
description: Install optional bare Sokosumi slash-command aliases such as /hannah, /elena, /research, and /market.
---

# Install Sokosumi Shortcuts

This command creates optional standalone slash-command symlinks in `.claude/commands` so users can invoke `/hannah`, `/elena`, `/research`, `/market`, `/agents`, `/jobs`, and `/tasks` without the plugin namespace.

Ask for confirmation before running the helper because it writes files in the current project. Then run:

```bash
sokosumi-plugin-link-shortcuts --project
```

Use `--user` instead of `--project` only when the user explicitly wants global aliases in `~/.claude/commands`.

If a target command already exists and is not a symlink, the helper will skip it. After installation, ask the user to run `/reload-plugins` or restart Claude Code if the aliases do not appear immediately.
