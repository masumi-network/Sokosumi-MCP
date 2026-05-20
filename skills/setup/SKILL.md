---
description: Set up or troubleshoot the Sokosumi Claude Code plugin, MCP authentication, and optional bare skill aliases such as /hannah and /elena.
---

# Sokosumi Setup

Use this when the user wants to install, authenticate, troubleshoot, or create short aliases for the Sokosumi plugin.

Checklist:

1. Confirm the plugin is loaded. Installed plugin skills are namespaced, for example `/sokosumi:hannah`.
2. For MCP auth, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. To create bare aliases like `/hannah`, run `sokosumi-plugin-link-shortcuts --project` with the Bash tool after explicit user confirmation. Use `--user` only if the user wants global aliases.
4. The helper symlinks plugin skill directories into `.claude/skills`, so bare standalone skills become `/hannah`, `/elena`, `/research`, `/market`, `/agents`, `/jobs`, and `/tasks`.
5. After aliases are created, tell the user to run `/reload-plugins` or restart Claude Code if the skills do not appear immediately.

Never write API keys or OAuth tokens into plugin files, `.claude/skills`, git commits, or logs.
