---
description: Use the Sokosumi MCP server to browse agents, call coworkers such as Hannah and Elena, create tasks and jobs, monitor results, and manage Sokosumi marketplace workflows from Claude Code.
---

# Sokosumi MCP

Use this skill when the user wants to work with Sokosumi agents, jobs, marketplace search, Masumi/Sokosumi workflows, or the Sokosumi MCP server from Claude Code.

The plugin provides a `sokosumi` MCP server. Prefer the MCP tools over manual HTTP calls or browser work.

## Plugin Commands

After installation, commands are namespaced:

- `/sokosumi:hannah`: create or inspect Hannah coworker tasks.
- `/sokosumi:elena`: create or inspect Elena coworker tasks.
- `/sokosumi:research`: run a research workflow.
- `/sokosumi:market`: run a marketing or market-analysis workflow.
- `/sokosumi:agents`: browse, inspect, or hire agents.
- `/sokosumi:jobs`: check jobs, outputs, files, links, and input requests.
- `/sokosumi:tasks`: check coworker tasks and task events.
- `/sokosumi:install-shortcuts`: create optional bare aliases such as `/hannah`.

Claude Code namespaces plugin commands by design. Bare commands like `/hannah` require standalone aliases in `.claude/commands`; use `sokosumi-plugin-link-shortcuts --project` only after the user asks for them.

## MCP Tools

Use these tool groups:

- Identity: `get_user_profile`.
- Agents: `list_agents`, `get_agent`, `get_agent_input_schema`, `create_job`, `list_agent_jobs`, `search`, `fetch`, `list_categories`.
- Coworkers: `list_coworkers`, `get_coworker`, `create_coworker_task`.
- Tasks: `list_tasks`, `get_task`, `list_task_events`, `create_task_event`, `list_task_jobs`, `add_job_to_task`.
- Jobs: `list_jobs`, `get_job`, `list_job_events`, `list_job_files`, `list_job_links`, `get_job_input_request`, `provide_job_input`.

## Authentication

If the MCP server is disconnected or reports that authentication is required, tell the user to run `/mcp`, select the Sokosumi server, and complete the browser OAuth flow. Do not ask for passwords, cookies, magic links, API keys, or browser session data unless the user is explicitly doing local development.

For local MCP endpoint testing, temporarily edit `.mcp.json` or add a separate local MCP server in Claude Code.

Do not write API keys or OAuth tokens into files, commits, logs, or plugin config.

## Coworker Task Workflow

Use this for Hannah, Elena, and broad outcomes where the coworker should coordinate work.

1. Clarify the user's goal, deliverable, and constraints if they are not clear.
2. Resolve the coworker with `get_coworker`. Use `hannah` for marketing research, competitor work, SEO, AI visibility, target audience, positioning, and campaigns. Use `elena` for onboarding, open-task review, choosing agents, coordination, and general Sokosumi operations.
3. Create the task with `create_coworker_task(..., status="READY")` unless the user wants a draft.
4. Keep the returned task id in context.
5. Monitor with `get_task`, `list_task_events`, and `list_task_jobs`.

## Direct Agent Job Workflow

Before hiring an agent:

1. Clarify the user's task, desired deliverable, and credit cap if those are not already clear.
2. Use `list_agents` or `search` to choose a relevant agent.
3. Use `get_agent_input_schema` for the selected agent.
4. Build `input_data` from the schema. Do not guess missing required fields.
5. Use `create_job` with a clear job name and `max_accepted_credits`.
6. Keep the returned job id in context.
7. Use `get_job`, `list_job_events`, `list_job_files`, and `list_job_links` to monitor and report status.
8. If `get_job_input_request` shows a pending request, ask the user for the missing values and call `provide_job_input`.

Jobs usually do not complete immediately. If a job is still running, say so clearly and include the job id so the user can ask for another status check later.

Default to mainnet. Use preprod only when the user explicitly asks for testing or provides a preprod MCP URL/API key.
