---
description: Install optional bare Sokosumi skill aliases such as /hannah, /elena, /research, /market, /agents, /jobs, and /tasks.
---

# Install Sokosumi Shortcuts

This skill creates optional standalone skill symlinks in `.claude/skills` so users can invoke `/hannah`, `/elena`, `/research`, `/market`, `/agents`, `/jobs`, and `/tasks` without the plugin namespace.

Ask for confirmation before running the helper because it writes files in the current project. Then run:

```bash
sokosumi-plugin-link-shortcuts --project
```

Use `--user` instead of `--project` only when the user explicitly wants global aliases in `~/.claude/skills`.

If a target skill already exists and is not a symlink, the helper will skip it. After installation, ask the user to run `/reload-plugins` or restart Claude Code if the aliases do not appear immediately.
