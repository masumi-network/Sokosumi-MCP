---
description: Create or inspect Elena coworker tasks in Sokosumi. Use Elena for onboarding, choosing agents, reviewing open work, coordinating workflows, and general Sokosumi operations.
---

# Elena

Task brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. Elena is the Sokosumi coworker for getting started, choosing the right agent or coworker, reviewing open tasks, coordinating workflows, and turning broad goals into executable next steps.

Workflow:

1. If the brief is empty, ask what the user wants Elena to help with.
2. Verify the connection with `get_user_profile`. If auth is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. If the user asks for status, open work, or what needs attention, use `list_tasks(coworker="elena")`, then `get_task`, `list_task_events`, and `list_task_jobs` for relevant tasks.
4. Otherwise resolve Elena with `get_coworker(coworker="elena")`.
5. Create a READY task with `create_coworker_task(coworker="elena", description=<brief>, name=<short title>, status="READY")`.
6. Return the task id, coworker, status, and next monitoring step.
