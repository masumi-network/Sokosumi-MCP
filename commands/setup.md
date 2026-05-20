---
description: Set up or troubleshoot the Sokosumi Claude Code plugin, MCP authentication, and optional bare slash-command aliases.
---

# Sokosumi Setup

Use this when the user wants to install, authenticate, troubleshoot, or create short aliases for the Sokosumi plugin.

Checklist:

1. Confirm the plugin is loaded. The installed plugin namespace is `sokosumi`, so commands look like `/sokosumi:hannah`.
2. For MCP auth, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. To create bare aliases like `/hannah`, run `sokosumi-plugin-link-shortcuts --project` with the Bash tool after explicit user confirmation. Use `--user` only if the user wants global aliases.
4. After aliases are created, tell the user to run `/reload-plugins` or restart Claude Code if the commands do not appear immediately.

Never write API keys or OAuth tokens into plugin files, `.claude/commands`, git commits, or logs.
