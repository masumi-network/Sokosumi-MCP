---
description: Create or inspect Hannah coworker tasks in Sokosumi. Use Hannah for competitor research, SEO and AI visibility analysis, audience research, positioning, campaigns, and marketing strategy.
---

# Hannah

Task brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. Hannah is the Sokosumi coworker for marketing and growth research: competitors, SEO, AI visibility, target audience analysis, media behavior, positioning, content direction, and campaign planning.

Workflow:

1. If the brief is empty, ask for the task goal, target market or product, desired deliverable, and constraints.
2. Verify the connection with `get_user_profile`. If auth is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. Resolve Hannah with `get_coworker(coworker="hannah")`; if needed, use `list_coworkers(search="hannah")`.
4. Create a READY task with `create_coworker_task(coworker="hannah", description=<brief>, name=<short title>, status="READY")`.
5. If the task was created with status READY, immediately start background monitoring: invoke the `sokosumi:watch` skill with the new task id. Do not wait for the task to finish.
6. Return the task id, coworker, status, and tell the user it is now being watched in the background and you will report back when it is done.

If the user asks about existing Hannah work, use `list_tasks(coworker="hannah")`, `get_task`, `list_task_events`, and `list_task_jobs`.
