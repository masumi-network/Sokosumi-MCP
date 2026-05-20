---
description: Check Sokosumi jobs, job events, outputs, files, links, and pending input requests.
---

# Sokosumi Jobs

Request: "$ARGUMENTS"

Use the `sokosumi` MCP server.

If the request includes a job id, call `get_job`, then use `list_job_events`, `list_job_files`, `list_job_links`, and `get_job_input_request` when useful. If there is no job id, call `list_jobs` and summarize the most relevant open or recent jobs.

If a job is awaiting input, explain the requested fields and ask the user for the missing values before calling `provide_job_input`.
