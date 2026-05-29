---
description: Browse, search, inspect, or hire Sokosumi marketplace agents through MCP.
---

# Sokosumi Agents

Request: "$ARGUMENTS"

Use the `sokosumi` MCP server.

Workflow:

1. Verify the connection with `get_user_profile` unless another Sokosumi MCP tool already succeeded in this turn.
2. For discovery, call `list_agents`, `list_categories`, or `search`.
3. For a specific agent, call `get_agent` and `get_agent_input_schema`.
4. To hire an agent, confirm the deliverable and credit cap, ask for missing required schema fields, call `create_job`, then start `sokosumi:watch` if the job is still running.
5. Return the job id, agent, status, and tell the user whether it is being watched in the background.

Use coworker tasks instead of direct jobs when the user has a broad outcome that needs coordination.
