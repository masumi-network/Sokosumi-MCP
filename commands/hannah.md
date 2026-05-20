---
description: Create or inspect a Hannah coworker task. Use Hannah for competitor research, SEO analysis, target audience research, marketing strategy, and campaign work.
---

# Hannah

Task brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. Hannah is the preferred coworker for marketing research, competitor comparisons, SEO and AI visibility analysis, target audience analysis, media behavior, positioning, and campaign planning.

Workflow:

1. If the brief is empty, ask the user for the task goal and any constraints.
2. Verify authentication with `get_user_profile`. If authentication is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. Resolve Hannah with `get_coworker(coworker="hannah")`. If that fails, use `list_coworkers(search="hannah")`.
4. Create the task with `create_coworker_task(coworker="hannah", description=<brief>, name=<short descriptive title>, status="READY")`.
5. Report the task id, coworker, status, and what the user should ask next to check progress.

If the user asks about an existing Hannah task instead of creating one, use `list_tasks(coworker="hannah")`, `get_task`, and `list_task_events`.
