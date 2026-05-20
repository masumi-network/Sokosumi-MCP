---
description: Check Sokosumi coworker tasks, task events, and task-linked jobs.
---

# Sokosumi Tasks

Request: "$ARGUMENTS"

Use the `sokosumi` MCP server.

Workflow:

1. Verify the connection with `get_user_profile` unless another Sokosumi MCP tool already succeeded in this turn.
2. If the request includes a task id, call `get_task`, `list_task_events`, and `list_task_jobs`.
3. If no task id is present, call `list_tasks`, filtering by coworker or status when the user mentions one.
4. Summarize status, latest activity, linked jobs, and the next action. Keep task ids in the response.
