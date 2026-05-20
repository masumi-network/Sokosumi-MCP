---
description: Create or inspect an Elena coworker task. Use Elena for getting started, choosing agents, open-task review, workflow coordination, and general Sokosumi operations.
---

# Elena

Task brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. Elena is the preferred coworker for Sokosumi onboarding, choosing which agents or capabilities to use, reviewing open tasks, coordinating work, and turning loose business goals into executable tasks.

Workflow:

1. If the brief is empty, ask what the user wants Elena to help with.
2. Verify authentication with `get_user_profile`. If authentication is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. If the brief asks for current status, open tasks, or what needs attention, use `list_tasks(coworker="elena")`, then `get_task` and `list_task_events` for relevant tasks.
4. Otherwise resolve Elena with `get_coworker(coworker="elena")` and create a task with `create_coworker_task(coworker="elena", description=<brief>, name=<short descriptive title>, status="READY")`.
5. Report the task id, coworker, status, and next monitoring step.
