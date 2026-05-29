---
description: Start a Sokosumi marketing or market-analysis workflow. Use for campaign strategy, positioning, competitors, audience, SEO, AI visibility, and market research.
---

# Market

Market brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. For market and marketing work, prefer Hannah unless the user explicitly requests a direct specialist agent.

Workflow:

1. If the brief is empty, ask for the product or company, target market, desired deliverable, and credit cap if a direct job may be needed.
2. Verify the connection with `get_user_profile`. If auth is missing, tell the user to run `/mcp`, select `sokosumi`, and complete OAuth.
3. Resolve Hannah with `get_coworker(coworker="hannah")`.
4. Create a READY task with `create_coworker_task(coworker="hannah", description=<brief>, name=<short title>, status="READY")`.
5. If Hannah is unavailable, search agents with marketing, market research, SEO, audience, or competitor terms and follow the direct agent job workflow.
6. After creating a READY task or direct job, immediately start background monitoring with `sokosumi:watch` using the task or job id. Do not wait for the work to finish.
7. Return the task or job id, status, and tell the user it is being watched in the background.
