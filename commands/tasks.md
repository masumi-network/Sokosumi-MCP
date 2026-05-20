---
description: Check Sokosumi coworker tasks, task events, and task jobs.
---

# Sokosumi Tasks

Request: "$ARGUMENTS"

Use the `sokosumi` MCP server.

If the request includes a task id, call `get_task`, `list_task_events`, and `list_task_jobs`. If no task id is present, call `list_tasks`, optionally filtering by coworker name or status when the user mentions one.

Summarize status, latest activity, linked jobs, and the next action. Keep task ids in the response.
