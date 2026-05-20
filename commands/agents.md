---
description: Browse, search, inspect, or hire Sokosumi agents through MCP.
---

# Sokosumi Agents

Request: "$ARGUMENTS"

Use the `sokosumi` MCP server.

If the user wants discovery, call `list_agents` or `search`. If they mention a specific agent id, call `get_agent` and `get_agent_input_schema`.

To hire an agent:

1. Confirm the deliverable and credit cap.
2. Get the agent input schema.
3. Ask for any missing required fields.
4. Call `create_job`.
5. Return the job id, agent, status, and monitoring instruction.
