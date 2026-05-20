---
description: Route Sokosumi work to the right MCP workflow. Use this for general Sokosumi marketplace, agent, coworker, task, or job requests.
---

# Sokosumi

User request: "$ARGUMENTS"

Use the `sokosumi` MCP server. First verify the connection with `get_user_profile` unless another Sokosumi MCP tool has already succeeded in this turn. If authentication is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.

If no request was provided, show the available shortcuts briefly:

- `/sokosumi:hannah` for marketing research, competitors, SEO, audience analysis, and campaign work.
- `/sokosumi:elena` for getting started, open-task review, operational help, and choosing agents.
- `/sokosumi:research` for research-agent discovery or research jobs.
- `/sokosumi:market` for marketing and market-analysis tasks.
- `/sokosumi:agents`, `/sokosumi:jobs`, and `/sokosumi:tasks` for direct management.

For a broad business outcome, prefer a coworker task with `create_coworker_task`. For a narrow single deliverable from one specialist, use `list_agents` or `search`, then `get_agent_input_schema`, then `create_job`. Always keep returned task ids and job ids in the final response.
