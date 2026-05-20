---
description: Start a Sokosumi research workflow. Use for research briefs, competitor analysis, market scans, source gathering, audience research, and one-off research agent jobs.
---

# Research

Research brief: "$ARGUMENTS"

Use the `sokosumi` MCP server.

Default path:

1. If the brief is empty, ask for the research question, desired output format, and credit cap.
2. For broad marketing or business research, prefer Hannah: call `create_coworker_task(coworker="hannah", description=<brief>, name=<short title>, status="READY")`.
3. For a narrow single-agent research job, use `search(query="research " + <brief>)` or `list_agents`, choose the best available research agent, call `get_agent_input_schema`, ask for missing required fields, then call `create_job`.
4. Report the task id or job id and expected follow-up.

Do not fabricate sources or agent capabilities. Use the marketplace data returned by Sokosumi.
