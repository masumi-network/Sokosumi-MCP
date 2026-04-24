#!/usr/bin/env python3
"""
Thorough test suite for the Sokosumi MCP server.

Covers:
  1. Tool registration - every expected tool is present with correct params.
  2. Auth gating - every tool returns an error dict when unauthenticated.
  3. API call correctness - mocks httpx at the transport layer and verifies
     each tool hits the right METHOD + PATH and wraps the response.
  4. Payload correctness - create_job / add_job_to_task / task updates use
     the new `maxCredits` + `inputSchema` fields (not the old broken names).
  5. Concurrency - fetch() issues its two requests in parallel.
  6. Client reuse - _api_request reuses the shared AsyncClient.

Run:  python test_tools.py
Exit 0 on success, 1 on any failure.
"""

import asyncio
import inspect
import sys
import time
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import httpx

# Import the server module (registers all @mcp.tool handlers).
import server


# ---------- tiny test harness ------------------------------------------------

_PASSED: List[str] = []
_FAILED: List[Tuple[str, str]] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        _PASSED.append(name)
        print(f"  \u2713 {name}")
    else:
        _FAILED.append((name, detail))
        print(f"  \u2717 {name}  ->  {detail}")


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


# ---------- expected tool catalog -------------------------------------------

EXPECTED_TOOLS = {
    # Agents
    "list_agents": [],
    "get_agent_input_schema": ["agent_id"],
    "list_agent_jobs": ["agent_id"],
    # Jobs
    "create_job": ["agent_id", "input_schema", "input_data", "max_credits", "name"],
    "list_jobs": [],
    "get_job": ["job_id"],
    "get_job_events": ["job_id"],
    "get_job_files": ["job_id"],
    "get_job_links": ["job_id"],
    "get_job_input_request": ["job_id"],
    "submit_job_input": ["job_id", "event_id", "input_data"],
    # Tasks
    "list_tasks": [],
    "get_task": ["task_id"],
    "create_task": ["name", "description", "coworker_id", "status"],
    "update_task": ["task_id", "name", "description", "status"],
    "delete_task": ["task_id"],
    "list_task_jobs": ["task_id"],
    "add_job_to_task": ["task_id", "agent_id", "input_schema", "input_data", "max_credits", "name"],
    "list_task_events": ["task_id"],
    "create_task_event": ["task_id", "status", "comment"],
    # Coworkers
    "list_coworkers": ["scope", "capability"],
    "get_coworker": ["coworker_id"],
    "get_current_coworker": [],
    "create_coworker": [
        "name", "caption", "company", "company_logo", "url", "base_url",
        "description", "image", "capabilities", "priority", "metadata",
    ],
    "update_coworker": [
        "coworker_id", "name", "caption", "company", "company_logo", "url",
        "base_url", "description", "image", "capabilities", "priority", "metadata",
    ],
    "create_coworker_api_key": ["coworker_id", "name", "expires_at"],
    # Categories
    "list_categories": [],
    "get_category": ["category_id_or_slug"],
    # User
    "get_user_profile": [],
    # ChatGPT compat
    "search": ["query"],
    "fetch": ["id"],
}


# ---------- mocked httpx transport ------------------------------------------

class MockTransport(httpx.AsyncBaseTransport):
    """
    Captures every request and returns programmed responses.

    Programmed via `queue` which maps (METHOD, PATH) or substring to a
    response tuple: (status_code, json_body). Unmatched calls get 200 {}.
    """

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self.queue: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        self._latency: float = 0.0

    def program(self, method: str, path_substr: str, status: int, body: Dict[str, Any]) -> None:
        self.queue[f"{method}:{path_substr}"] = (status, body)

    def set_latency(self, seconds: float) -> None:
        self._latency = seconds

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json_mod
        path = request.url.path
        method = request.method
        try:
            body = (
                _json_mod.loads(request.content.decode()) if request.content else None
            )
        except Exception:
            body = None
        self.calls.append((method, path, {"body": body, "query": dict(request.url.params)}))

        if self._latency:
            await asyncio.sleep(self._latency)

        # Look for programmed match (substring on path)
        for key, (status, payload) in self.queue.items():
            m, substr = key.split(":", 1)
            if m == method and substr in path:
                return httpx.Response(status, json=payload)
        return httpx.Response(200, json={"data": []})


def _install_mock(network: str = "mainnet") -> MockTransport:
    """Replace the shared client with one using a mock transport."""
    transport = MockTransport()
    base = "https://app.sokosumi.com/api" if network == "mainnet" else "https://preprod.sokosumi.com/api"
    # Close any existing client so _get_http_client won't reuse it.
    existing = server._http_clients.pop(network, None)
    if existing is not None:
        # Do not await; tests run fresh. Just drop the reference.
        pass
    server._http_clients[network] = httpx.AsyncClient(
        base_url=base, transport=transport, timeout=5.0
    )
    return transport


async def _run_tool(tool_name: str, **kwargs: Any) -> Any:
    """Invoke a tool by calling the underlying Python function directly.

    FastMCP's tool manager wraps results; calling the function gives us the
    raw dict we want to assert on.
    """
    fn = getattr(server, tool_name)
    return await fn(**kwargs)


# ---------- tests -----------------------------------------------------------

async def test_tool_registration() -> None:
    _section("1. Tool registration")
    mgr = server.mcp._tool_manager
    registered = set(mgr._tools.keys())
    expected = set(EXPECTED_TOOLS.keys())

    missing = expected - registered
    extra = registered - expected
    _check("all expected tools registered", not missing, f"missing: {missing}")
    _check("no unexpected tools registered", not extra, f"extra: {extra}")
    _check("total tool count is 31", len(registered) == 31, f"got {len(registered)}")

    # Every tool function has the expected parameter names
    for tool_name, expected_params in EXPECTED_TOOLS.items():
        fn = getattr(server, tool_name, None)
        if fn is None:
            _check(f"signature: {tool_name}", False, "function missing on module")
            continue
        sig = inspect.signature(fn)
        got = [p for p in sig.parameters if p != "self"]
        _check(
            f"signature: {tool_name}",
            got == expected_params,
            f"expected {expected_params}, got {got}",
        )


async def test_auth_gating() -> None:
    _section("2. Auth gating - every tool returns error when unauthenticated")
    # Reset api key context
    server.api_keys.pop("current", None)
    server.current_api_key.set(None)

    # A representative sample (testing every single one would be noisy).
    samples: List[Tuple[str, Dict[str, Any]]] = [
        ("list_agents", {}),
        ("get_job", {"job_id": "j1"}),
        ("create_job", {
            "agent_id": "a1", "input_schema": {}, "input_data": {}
        }),
        ("create_task", {"name": "t"}),
        ("list_coworkers", {}),
        ("list_categories", {}),
        ("get_user_profile", {}),
    ]
    for tool_name, kwargs in samples:
        result = await _run_tool(tool_name, **kwargs)
        # Tools return either a dict with "error" key, or ChatGPT content-wrapped error
        has_error = False
        if isinstance(result, dict):
            has_error = "error" in result
        _check(f"{tool_name}: errors without auth", has_error, repr(result)[:200])


async def test_http_correctness() -> None:
    _section("3. HTTP method + path correctness (mocked transport)")
    transport = _install_mock()
    server.api_keys["current"] = "TEST_KEY"
    server.current_api_key.set("TEST_KEY")
    server.networks["current"] = "mainnet"
    server.current_network.set("mainnet")

    cases: List[Tuple[str, Dict[str, Any], str, str]] = [
        ("list_agents", {}, "GET", "/v1/agents"),
        ("get_agent_input_schema", {"agent_id": "A"}, "GET", "/v1/agents/A/input-schema"),
        ("list_agent_jobs", {"agent_id": "A"}, "GET", "/v1/agents/A/jobs"),
        ("list_jobs", {}, "GET", "/v1/jobs"),
        ("get_job", {"job_id": "J"}, "GET", "/v1/jobs/J"),
        ("get_job_events", {"job_id": "J"}, "GET", "/v1/jobs/J/events"),
        ("get_job_files", {"job_id": "J"}, "GET", "/v1/jobs/J/files"),
        ("get_job_links", {"job_id": "J"}, "GET", "/v1/jobs/J/links"),
        ("get_job_input_request", {"job_id": "J"}, "GET", "/v1/jobs/J/input-request"),
        ("list_tasks", {}, "GET", "/v1/tasks"),
        ("get_task", {"task_id": "T"}, "GET", "/v1/tasks/T"),
        ("list_task_jobs", {"task_id": "T"}, "GET", "/v1/tasks/T/jobs"),
        ("list_task_events", {"task_id": "T"}, "GET", "/v1/tasks/T/events"),
        ("delete_task", {"task_id": "T"}, "DELETE", "/v1/tasks/T"),
        ("list_coworkers", {}, "GET", "/v1/coworkers"),
        ("get_coworker", {"coworker_id": "C"}, "GET", "/v1/coworkers/C"),
        ("get_current_coworker", {}, "GET", "/v1/coworkers/me"),
        ("list_categories", {}, "GET", "/v1/categories"),
        ("get_category", {"category_id_or_slug": "slug-x"}, "GET", "/v1/categories/slug-x"),
        ("get_user_profile", {}, "GET", "/v1/users/me"),
    ]
    for tool_name, kwargs, expected_method, expected_path in cases:
        before = len(transport.calls)
        await _run_tool(tool_name, **kwargs)
        new_calls = transport.calls[before:]
        ok = any(c[0] == expected_method and c[1].endswith(expected_path) for c in new_calls)
        _check(
            f"{tool_name}: {expected_method} {expected_path}",
            ok,
            f"saw {new_calls}",
        )


async def test_payload_shapes() -> None:
    _section("4. Payload correctness (new API contract)")
    transport = _install_mock()
    server.api_keys["current"] = "TEST_KEY"
    server.current_api_key.set("TEST_KEY")
    transport.program("POST", "/v1/agents/A/jobs", 201, {"data": {"id": "J"}})
    transport.program("POST", "/v1/tasks/T/jobs", 201, {"data": {"id": "J"}})
    transport.program("PATCH", "/v1/tasks/T", 200, {"data": {"id": "T"}})
    transport.program("POST", "/v1/tasks", 201, {"data": {"id": "T"}})
    transport.program("POST", "/v1/jobs/J/inputs", 200, {"success": True})

    # create_job must send inputSchema + inputData + maxCredits (NOT maxAcceptedCredits)
    await _run_tool(
        "create_job",
        agent_id="A",
        input_schema={"fields": []},
        input_data={"x": 1},
        max_credits=42,
        name="Hello",
    )
    body = next(
        c[2]["body"] for c in transport.calls
        if c[0] == "POST" and c[1].endswith("/v1/agents/A/jobs")
    )
    _check("create_job sends maxCredits", body.get("maxCredits") == 42, f"body={body}")
    _check("create_job sends inputSchema", body.get("inputSchema") == {"fields": []}, f"body={body}")
    _check("create_job sends inputData", body.get("inputData") == {"x": 1}, f"body={body}")
    _check("create_job sends name", body.get("name") == "Hello", f"body={body}")
    _check("create_job omits maxAcceptedCredits", "maxAcceptedCredits" not in body, f"body={body}")

    # add_job_to_task — same contract
    await _run_tool(
        "add_job_to_task",
        task_id="T", agent_id="A",
        input_schema={"a": 1}, input_data={"b": 2}, max_credits=10, name="n",
    )
    body = next(
        c[2]["body"] for c in transport.calls
        if c[0] == "POST" and c[1].endswith("/v1/tasks/T/jobs")
    )
    _check("add_job_to_task sends agentId + maxCredits",
           body.get("agentId") == "A" and body.get("maxCredits") == 10, f"body={body}")

    # create_task with all fields
    await _run_tool("create_task", name="Task1", description="d", coworker_id="cw", status="DRAFT")
    body = next(
        c[2]["body"] for c in transport.calls
        if c[0] == "POST" and c[1].endswith("/v1/tasks") and not c[1].endswith("/jobs")
    )
    _check("create_task payload", body == {
        "name": "Task1", "description": "d", "coworkerId": "cw", "status": "DRAFT"
    }, f"body={body}")

    # update_task - only sends provided fields (PATCH semantics)
    await _run_tool("update_task", task_id="T", status="COMPLETED")
    body = next(
        c[2]["body"] for c in transport.calls
        if c[0] == "PATCH" and c[1].endswith("/v1/tasks/T")
    )
    _check("update_task sparse PATCH", body == {"status": "COMPLETED"}, f"body={body}")

    # submit_job_input
    await _run_tool("submit_job_input", job_id="J", event_id="E", input_data={"ans": "yes"})
    body = next(
        c[2]["body"] for c in transport.calls
        if c[0] == "POST" and c[1].endswith("/v1/jobs/J/inputs")
    )
    _check("submit_job_input body", body == {"eventId": "E", "inputData": {"ans": "yes"}}, f"body={body}")

    # create_task_event requires at least status or comment
    result = await _run_tool("create_task_event", task_id="T")
    _check("create_task_event rejects empty", "error" in result, repr(result)[:200])


async def test_error_handling() -> None:
    _section("5. Error handling (non-2xx responses)")
    transport = _install_mock()
    server.api_keys["current"] = "TEST_KEY"
    server.current_api_key.set("TEST_KEY")
    transport.program("GET", "/v1/jobs/MISSING", 404, {"error": "not found"})

    result = await _run_tool("get_job", job_id="MISSING")
    _check("404 surfaces as error dict", isinstance(result, dict) and "error" in result, repr(result)[:200])
    _check("404 includes status code", "404" in result.get("error", ""), repr(result)[:200])


async def test_fetch_parallel() -> None:
    _section("6. fetch() concurrency + client reuse")
    transport = _install_mock()
    transport.set_latency(0.15)  # 150ms each - serial would be ~300ms
    transport.program("GET", "/v1/agents", 200, {"data": [{"id": "A", "name": "Agent A", "price": 10}]})
    transport.program("GET", "/v1/agents/A/input-schema", 200, {"data": {"fields": []}})
    server.api_keys["current"] = "TEST_KEY"
    server.current_api_key.set("TEST_KEY")

    t0 = time.perf_counter()
    result = await _run_tool("fetch", id="A")
    elapsed = time.perf_counter() - t0

    _check(
        "fetch runs its two requests concurrently (< 250ms)",
        elapsed < 0.25,
        f"took {elapsed*1000:.0f}ms",
    )
    _check("fetch returned ChatGPT content wrapper",
           isinstance(result, dict) and "content" in result,
           repr(result)[:200])


async def test_client_reuse() -> None:
    _section("7. HTTP client is reused across requests")
    # Install fresh mock, make several calls, assert client identity unchanged.
    transport = _install_mock()
    server.api_keys["current"] = "TEST_KEY"
    server.current_api_key.set("TEST_KEY")
    client_before = server._http_clients.get("mainnet")
    await _run_tool("list_agents")
    await _run_tool("list_jobs")
    await _run_tool("list_tasks")
    client_after = server._http_clients.get("mainnet")
    _check(
        "shared client reused across calls",
        client_before is client_after and client_before is not None,
        "client was recreated",
    )
    _check(
        "three tool calls = three HTTP requests (no extra chatter)",
        len(transport.calls) == 3,
        f"saw {len(transport.calls)} calls",
    )


async def test_search_filtering() -> None:
    _section("8. search() keyword filtering + format")
    transport = _install_mock()
    server.api_keys["current"] = "TEST_KEY"
    server.current_api_key.set("TEST_KEY")
    transport.program("GET", "/v1/agents", 200, {"data": [
        {"id": "1", "name": "Image Generator", "description": "makes images", "price": 5, "tags": []},
        {"id": "2", "name": "Text Summarizer", "description": "summarizes text", "price": 3, "tags": []},
    ]})
    result = await _run_tool("search", query="image")
    import json as _json
    payload = _json.loads(result["content"][0]["text"])
    _check(
        "search filters to matching agent",
        len(payload["results"]) == 1 and payload["results"][0]["id"] == "1",
        repr(payload),
    )


# ---------- main ------------------------------------------------------------

async def main() -> int:
    await test_tool_registration()
    await test_auth_gating()
    await test_http_correctness()
    await test_payload_shapes()
    await test_error_handling()
    await test_fetch_parallel()
    await test_client_reuse()
    await test_search_filtering()

    print("\n" + "=" * 60)
    print(f"PASSED: {len(_PASSED)}   FAILED: {len(_FAILED)}")
    if _FAILED:
        print("\nFailures:")
        for name, detail in _FAILED:
            print(f"  - {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
