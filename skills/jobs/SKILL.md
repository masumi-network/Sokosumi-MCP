---
description: Check Sokosumi jobs, job events, outputs, files, links, and pending input requests.
---

# Sokosumi Jobs

Request: "$ARGUMENTS"

Use the `sokosumi` MCP server.

Workflow:

1. Verify the connection with `get_user_profile` unless another Sokosumi MCP tool already succeeded in this turn.
2. If the request includes a job id, call `get_job`.
3. Use `list_job_events`, `list_job_files`, `list_job_links`, and `get_job_input_request` when useful.
4. If no job id is present, call `list_jobs` and summarize the most relevant open or recent jobs.
5. If a job is awaiting input, explain the requested fields and ask the user for missing values before calling `provide_job_input`.
