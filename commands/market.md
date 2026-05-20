---
description: Start a Sokosumi marketing or market-analysis workflow. Use for campaign strategy, positioning, competitors, audience, SEO, and AI visibility analysis.
---

# Market

Market brief: "$ARGUMENTS"

Use the `sokosumi` MCP server. For market and marketing work, prefer Hannah unless the user explicitly requests a direct specialist agent.

Workflow:

1. If the brief is empty, ask for the product/company, target market, deliverable, and credit cap if relevant.
2. Use `get_coworker(coworker="hannah")` to verify Hannah is available.
3. Create a READY task with `create_coworker_task(coworker="hannah", description=<brief>, name=<short title>, status="READY")`.
4. If Hannah is unavailable, search agents with marketing, market research, SEO, audience, or competitor terms and follow the direct agent job workflow.
5. Return the task or job id and status.
