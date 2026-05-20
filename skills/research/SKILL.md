---
description: Start a Sokosumi research workflow. Use for research briefs, competitor analysis, market scans, source gathering, audience research, and research-agent jobs.
---

# Research

Research brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. Prefer a coworker task when the brief is broad or needs coordination; prefer a direct agent job when the user asks for one narrow deliverable from one specialist.

Workflow:

1. If the brief is empty, ask for the research question, desired output format, and credit cap if a direct job may be needed.
2. Verify the connection with `get_user_profile`. If auth is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. For broad marketing, customer, competitor, or business research, use Hannah: `create_coworker_task(coworker="hannah", description=<brief>, name=<short title>, status="READY")`.
4. For a direct research-agent job, use `search(query="research " + <brief>)` or `list_agents`, choose a relevant agent, call `get_agent_input_schema`, ask for missing required fields, then call `create_job`.
5. Return the task id or job id and the expected follow-up.

Do not fabricate sources or capabilities. Use the marketplace and job data returned by Sokosumi.
