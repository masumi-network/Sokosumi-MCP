#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Using Streamable HTTP transport (the modern standard).
OAuth 2.1 authentication delegates to Sokosumi's OAuth provider.
"""

import os
import logging
import sys
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, RedirectResponse, HTMLResponse
from starlette.routing import Route
from contextvars import ContextVar

from oauth import (
    get_protected_resource_metadata,
    get_authorization_server_metadata,
    get_www_authenticate_header,
    build_proxy_url,
    get_jwks_url,
    normalize_network,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

MAINNET_API_BASE_URL = "https://api.sokosumi.com"
PREPROD_API_BASE_URL = "https://preprod.api.sokosumi.com"

# Create the FastMCP server instance with transport security configured for Railway
# This allows the custom domain mcp.sokosumi.com to be used
mcp = FastMCP(
    "sokosumi-mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*", "mcp.sokosumi.com", "mcp.sokosumi.com:*"],
        allowed_origins=["https://mcp.sokosumi.com", "https://mcp.sokosumi.com:*", "http://localhost:*"],
    )
)

# Context variables to store request-specific data
current_api_key: ContextVar[Optional[str]] = ContextVar('current_api_key', default=None)
current_network: ContextVar[Optional[str]] = ContextVar('current_network', default=None)
current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar('current_user', default=None)

_http_app = None


def _default_network() -> str:
    """Return the configured default network for non-HTTP/stdio usage."""
    return normalize_network(os.environ.get("SOKOSUMI_NETWORK"))


def _default_api_key() -> Optional[str]:
    """Return the configured default API key for non-HTTP/stdio usage."""
    api_key = os.environ.get("SOKOSUMI_API_KEY", "").strip()
    return api_key or None

# Middleware for authentication (API key or OAuth Bearer token)
class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware supporting dual auth:
    1. API key (query param ?api_key= or header x-api-key)
    2. OAuth 2.1 Bearer token (Authorization: Bearer <token>)

    Priority: API key takes precedence over Bearer token.
    If neither is provided/valid, returns 401 with WWW-Authenticate header.
    """

    async def dispatch(self, request: Request, call_next):
        api_token = None
        network_token = None
        user_token = None

        try:
            # Handle well-known and OAuth endpoints without authentication
            if request.url.path.startswith("/.well-known/") or request.url.path.startswith("/oauth/"):
                return await call_next(request)

            # Extract network from query parameters (preprod or mainnet)
            network = normalize_network(request.query_params.get('network'))
            network_token = current_network.set(network)
            logger.info(f"Using network: {network}")

            # Try API key authentication first
            api_key = self._extract_api_key(request)
            if api_key:
                api_token = current_api_key.set(api_key)
                logger.info(f"Authenticated via API key: {api_key[:8]}..." if len(api_key) > 8 else "API key auth")
                response = await call_next(request)
                return self._cleanup_and_return(response, api_token, network_token, user_token)

            # Try Bearer token authentication
            bearer_token = self._extract_bearer_token(request)
            if bearer_token:
                try:
                    user_payload = await _validate_bearer_token(bearer_token, network)
                    if not user_payload:
                        logger.warning("Invalid upstream bearer token")
                        return self._unauthorized_response("Invalid or expired token", network)

                    user_token = current_user.set(user_payload)
                    api_token = current_api_key.set(bearer_token)
                    logger.info(f"Authenticated via bearer token for user: {user_payload.get('id', 'unknown')}")
                    response = await call_next(request)
                    return self._cleanup_and_return(response, api_token, network_token, user_token)
                except UpstreamAuthError as e:
                    logger.error(f"Bearer token validation error: {e}")
                    return JSONResponse(
                        status_code=502,
                        content={"error": "Bad Gateway", "detail": "Authentication upstream unavailable"},
                    )
                except Exception as e:
                    logger.error(f"Unexpected bearer validation error: {e}")
                    return self._unauthorized_response("Token validation failed", network)

            # No valid authentication - return 401
            # Only require auth for /mcp endpoint, allow other endpoints through
            if request.url.path.startswith("/mcp"):
                return self._unauthorized_response("Authentication required", network)

            # Allow non-MCP endpoints through (health checks, etc.)
            response = await call_next(request)
            return self._cleanup_and_return(response, api_token, network_token, user_token)

        except Exception as e:
            logger.error(f"Middleware error: {e}")
            return await call_next(request)

    def _extract_api_key(self, request: Request) -> Optional[str]:
        """Extract API key from query param or header."""
        # Check query parameter first
        api_key = request.query_params.get('api_key')
        if api_key:
            return api_key

        # Check x-api-key header
        api_key = request.headers.get('x-api-key')
        if api_key:
            return api_key

        return None

    def _extract_bearer_token(self, request: Request) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        auth_header = request.headers.get('authorization', '')
        if auth_header.lower().startswith('bearer '):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None

    def _unauthorized_response(self, detail: str, network: Optional[str] = None) -> Response:
        """Return a 401 Unauthorized response with WWW-Authenticate header."""
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "detail": detail},
            headers={"WWW-Authenticate": get_www_authenticate_header(network)},
        )

    def _cleanup_and_return(
        self,
        response: Response,
        api_token,
        network_token,
        user_token,
    ) -> Response:
        """Clean up context variables and return response."""
        if api_token:
            try:
                current_api_key.reset(api_token)
            except:
                pass
        if network_token:
            try:
                current_network.reset(network_token)
            except:
                pass
        if user_token:
            try:
                current_user.reset(user_token)
            except:
                pass
        return response

# Helper function to get the base URL based on network
def get_base_url(network: Optional[str] = None) -> str:
    """
    Get the base API URL based on the network.

    Args:
        network: The network to use (preprod or mainnet). If None, uses context or defaults to mainnet.

    Returns:
        The base URL for the API
    """
    if network is None:
        network = normalize_network(current_network.get() or _default_network())

    if network == 'preprod':
        return PREPROD_API_BASE_URL
    else:
        return MAINNET_API_BASE_URL

# Helper function to get API key/token
def get_current_api_key() -> Optional[str]:
    """
    Get the current API key or OAuth token from context.

    Returns:
        The API key/token or None if not found
    """
    return current_api_key.get() or _default_api_key()


def get_auth_headers() -> Dict[str, str]:
    """
    Get authentication headers for Sokosumi API calls.

    The current Sokosumi API (per OpenAPI spec) requires Bearer token
    authentication for both user credentials and coworker API keys.
    """
    token = get_current_api_key()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# Shared HTTP clients keyed by network. Reusing a client across calls avoids
# a fresh TLS handshake per request and enables HTTP/2 connection reuse.
_http_clients: Dict[str, httpx.AsyncClient] = {}


class UpstreamAuthError(RuntimeError):
    """Raised when the upstream auth/resource server cannot validate a token."""


def _get_http_client(network: str) -> httpx.AsyncClient:
    """Return (and lazily create) a shared AsyncClient for the given network."""
    client = _http_clients.get(network)
    if client is None or client.is_closed:
        base_url = (
            PREPROD_API_BASE_URL
            if network == "preprod"
            else MAINNET_API_BASE_URL
        )
        client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            http2=False,  # keep False unless h2 is added to requirements
        )
        _http_clients[network] = client
    return client


async def _validate_bearer_token(
    token: str,
    network: str,
) -> Optional[Dict[str, Any]]:
    """
    Validate a bearer token against the real Sokosumi API auth stack.

    The upstream `/v1/users/me` endpoint already accepts the same Better Auth
    OAuth access tokens and API keys used by the product, so using it here
    avoids maintaining a second token universe inside the MCP server.
    """
    client = _get_http_client(network)

    try:
        response = await client.get(
            "/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
    except httpx.HTTPError as e:
        raise UpstreamAuthError(str(e)) from e

    if response.status_code == 200:
        payload = response.json()
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                return data
        return None

    if response.status_code in {401, 403}:
        return None

    raise UpstreamAuthError(
        f"Unexpected status from /v1/users/me: {response.status_code}"
    )


async def _api_request(
    method: str,
    path: str,
    *,
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    expect_status: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Unified Sokosumi API request helper.

    Handles auth, error wrapping, and JSON parsing. Returns a dict with either
    the parsed response body, or an {"error": ..., "details": ...} shape.
    """
    api_key = get_current_api_key()
    if not api_key:
        return {"error": "Not authenticated. Provide ?api_key= or OAuth Bearer token."}

    network = normalize_network(current_network.get() or _default_network())
    client = _get_http_client(network)
    ok_statuses = expect_status or [200, 201, 204]

    try:
        response = await client.request(
            method,
            path,
            headers=get_auth_headers(),
            json=body if body is not None else None,
            params=params,
        )

        if response.status_code in ok_statuses:
            if response.status_code == 204 or not response.content:
                return {"success": True}
            try:
                return response.json()
            except Exception:
                return {"success": True, "raw": response.text}

        # Truncate huge error bodies to keep MCP responses small
        err_text = response.text
        if len(err_text) > 2000:
            err_text = err_text[:2000] + "... [truncated]"
        logger.error(
            f"Sokosumi API {method} {path} failed: {response.status_code} - {err_text}"
        )
        return {
            "error": f"Request failed: {response.status_code}",
            "details": err_text,
        }
    except httpx.TimeoutException as e:
        logger.error(f"Timeout calling {method} {path}: {e}")
        return {"error": "Request timed out", "details": str(e)}
    except Exception as e:
        logger.error(f"Error calling Sokosumi API {method} {path}: {e}")
        return {"error": "Failed to connect to Sokosumi API", "details": str(e)}


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Get the current authenticated user from bearer-token validation context.

    Returns:
        The user payload dict or None if not authenticated via bearer token
    """
    return current_user.get()


def is_authenticated() -> bool:
    """
    Check if the current request is authenticated (via API key or bearer token).

    Returns:
        True if authenticated, False otherwise
    """
    return get_current_api_key() is not None or get_current_user() is not None

# Resources
@mcp.resource("masumi://input-schema-standard")
def get_masumi_input_schema_standard() -> str:
    """
    Masumi Input Schema Standard documentation.

    Returns the MIP-003 standard for agent input schemas, which defines
    how agents should structure their input requirements.
    """
    return """
    # Masumi Input Schema Standard (MIP-003)

    Reference: https://github.com/masumi-network/masumi-improvement-proposals/blob/main/MIPs/MIP-003/MIP-003-Attachement-01.md

    This standard defines how agents should structure their input schemas for the Masumi/Sokosumi platform.

    ## Key Points:
    - Input schemas define the required and optional parameters for agent jobs
    - Each parameter has a type (string, number, boolean, array, object)
    - Parameters can have constraints (min/max values, patterns, etc.)
    - The schema must be validated before job submission

    Use this resource when:
    - You need to understand the expected format of agent input schemas
    - You encounter issues with input validation
    - You need to construct proper input data for job creation

    Always check the agent's specific input schema using get_agent_input_schema()
    before creating a job.
    """

# Prompts
@mcp.prompt("hire_agent")
def hire_agent_prompt() -> str:
    """
    Step-by-step guide for hiring an agent on the Sokosumi platform.

    This prompt provides the recommended workflow for successfully
    hiring and monitoring agent jobs.
    """
    return """
    # How to Hire an Agent on Sokosumi

    Follow these steps to successfully hire an agent:

    ## Step 1: Get the Agent's Input Schema
    First, retrieve the input schema for your chosen agent:
    ```
    get_agent_input_schema(agent_id="<AGENT_ID>")
    ```
    This tells you what parameters the agent requires.

    ## Step 2: Create the Job
    Submit a job with the required input data:
    ```
    create_job(
        agent_id="<AGENT_ID>",
        max_accepted_credits=<MAX_CREDITS>,
        input_data={...},  # Must match the input schema
        name="Optional job name"
    )
    ```
    Save the returned job_id for tracking.

    ## Step 3: Monitor Job Status
    Check the job status repeatedly until completion:
    ```
    get_job(job_id="<JOB_ID>")
    ```

    **Important timing notes:**
    - DO NOT check status immediately - wait at least 3 minutes after job creation
    - Jobs typically take AT MINIMUM 7 minutes to complete
    - Many jobs take much longer (15-30+ minutes or more)
    - Keep checking periodically until status shows:
      - "completed" (success - output will be available)
      - "failed" (job failed - check error details)
    - For long-running jobs, save the job_id and check back later rather than continuous polling
    - Consider checking every 5-10 minutes for jobs that take longer than expected

    ## Tips:
    - Always validate your input_data matches the schema before submission
    - Set max_accepted_credits appropriately based on the agent's pricing
    - Consider the job processing time when planning your workflow
    - Save job IDs for future reference
    """


@mcp.tool()
async def list_agents() -> Dict[str, Any]:
    """
    Lists all available AI agents with their pricing and capabilities.

    Returns a list of agents with fields such as id, name, description,
    status, price (credits required), tags, isNew, isShown.
    """
    return await _api_request("GET", "/v1/agents")


@mcp.tool()
async def get_agent_input_schema(agent_id: str) -> Dict[str, Any]:
    """
    Gets the required input schema for a specific agent.

    Args:
        agent_id: The ID of the agent to get the input schema for

    Returns:
        The input schema (and input_groups) describing required parameters.
        This schema must be passed back to create_job().
    """
    return await _api_request("GET", f"/v1/agents/{agent_id}/input-schema")

@mcp.tool()
async def create_job(
    agent_id: str,
    input_schema: Dict[str, Any],
    input_data: Dict[str, Any],
    max_credits: Optional[float] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a new job for a specific agent.

    You must first call get_agent_input_schema(agent_id) to obtain the exact
    input_schema for the agent - it must be passed back in the job creation
    payload so the server can validate input_data against it.

    Args:
        agent_id: The ID of the agent to create a job for
        input_schema: The agent's input schema (from get_agent_input_schema)
        input_data: Input data for the agent, matching the input schema
        max_credits: Maximum credits you're willing to pay (optional - uses agent default if omitted)
        name: Optional name for the job

    Returns:
        The created job details including job ID and status
    """
    body: Dict[str, Any] = {
        "inputSchema": input_schema,
        "inputData": input_data or {},
    }
    if max_credits is not None and max_credits > 0:
        body["maxCredits"] = max_credits
    if name:
        body["name"] = name

    return await _api_request("POST", f"/v1/agents/{agent_id}/jobs", body=body)

@mcp.tool()
async def get_job(job_id: str) -> Dict[str, Any]:
    """
    Retrieves status and results for a specific job.

    Args:
        job_id: The ID of the job to retrieve

    Returns:
        Job details including status, output, input, price, and timestamps.
    """
    return await _api_request("GET", f"/v1/jobs/{job_id}")


@mcp.tool()
async def list_jobs() -> Dict[str, Any]:
    """
    Lists all jobs belonging to the authenticated user across all agents.
    """
    return await _api_request("GET", "/v1/jobs")


@mcp.tool()
async def list_agent_jobs(agent_id: str) -> Dict[str, Any]:
    """
    Lists all jobs for a specific agent belonging to the authenticated user.

    Args:
        agent_id: The ID of the agent to list jobs for
    """
    return await _api_request("GET", f"/v1/agents/{agent_id}/jobs")


@mcp.tool()
async def get_job_events(job_id: str) -> Dict[str, Any]:
    """
    Retrieves lifecycle events for a specific job (status transitions, logs,
    input requests). Useful for debugging long-running jobs.

    Args:
        job_id: The ID of the job
    """
    return await _api_request("GET", f"/v1/jobs/{job_id}/events")


@mcp.tool()
async def get_job_files(job_id: str) -> Dict[str, Any]:
    """
    Retrieves file outputs produced by a completed job.

    Args:
        job_id: The ID of the job
    """
    return await _api_request("GET", f"/v1/jobs/{job_id}/files")


@mcp.tool()
async def get_job_links(job_id: str) -> Dict[str, Any]:
    """
    Retrieves link outputs produced by a completed job.

    Args:
        job_id: The ID of the job
    """
    return await _api_request("GET", f"/v1/jobs/{job_id}/links")


@mcp.tool()
async def get_job_input_request(job_id: str) -> Dict[str, Any]:
    """
    Checks if a running job is waiting for additional input from the user.
    Returns the input request (with eventId and schema) if one is pending,
    or an empty response if the job does not currently need input.

    Args:
        job_id: The ID of the job
    """
    return await _api_request("GET", f"/v1/jobs/{job_id}/input-request")


@mcp.tool()
async def submit_job_input(
    job_id: str,
    event_id: str,
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Provides additional input to a job that is waiting on user input.
    Call get_job_input_request first to get the event_id and required schema.

    Args:
        job_id: The ID of the job
        event_id: The ID of the event awaiting input (from get_job_input_request)
        input_data: Input data to provide, matching the requested schema
    """
    body = {"eventId": event_id, "inputData": input_data or {}}
    return await _api_request("POST", f"/v1/jobs/{job_id}/inputs", body=body)


@mcp.tool()
async def get_user_profile() -> Dict[str, Any]:
    """
    Gets the current user's profile information including id, name, email,
    terms acceptance, marketing opt-in, and account timestamps.
    """
    return await _api_request("GET", "/v1/users/me")


# ============================================================================
# Task tools (coworker orchestration)
# ============================================================================

@mcp.tool()
async def list_tasks() -> Dict[str, Any]:
    """
    Lists all tasks for the authenticated user. Tasks group related agent
    jobs together for multi-step workflows and coworker orchestration.
    """
    return await _api_request("GET", "/v1/tasks")


@mcp.tool()
async def get_task(task_id: str) -> Dict[str, Any]:
    """
    Retrieves a specific task by ID.

    Args:
        task_id: The ID of the task
    """
    return await _api_request("GET", f"/v1/tasks/{task_id}")


@mcp.tool()
async def create_task(
    name: Optional[str] = None,
    description: Optional[str] = None,
    coworker_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a new task for grouping agent jobs or orchestrating a coworker.

    Args:
        name: Task name (defaults to "New Task")
        description: Task description
        coworker_id: Optional coworker to assign the task to
        status: Initial status, 'DRAFT' or 'READY'
    """
    body: Dict[str, Any] = {
        "name": name or "New Task",
        "description": description or "",
    }
    if coworker_id:
        body["coworkerId"] = coworker_id
    if status:
        body["status"] = status
    return await _api_request("POST", "/v1/tasks", body=body)


@mcp.tool()
async def update_task(
    task_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Updates metadata of an existing task. Only provided fields are changed.

    Args:
        task_id: The ID of the task to update
        name: New task name
        description: New description
        status: New status (DRAFT, READY, IN_PROGRESS, COMPLETED, ...)
    """
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    return await _api_request("PATCH", f"/v1/tasks/{task_id}", body=body)


@mcp.tool()
async def delete_task(task_id: str) -> Dict[str, Any]:
    """
    Deletes a task. Associated jobs are not automatically deleted.

    Args:
        task_id: The ID of the task to delete
    """
    return await _api_request("DELETE", f"/v1/tasks/{task_id}")


@mcp.tool()
async def list_task_jobs(task_id: str) -> Dict[str, Any]:
    """
    Lists all jobs that belong to a specific task.

    Args:
        task_id: The ID of the task
    """
    return await _api_request("GET", f"/v1/tasks/{task_id}/jobs")


@mcp.tool()
async def add_job_to_task(
    task_id: str,
    agent_id: str,
    input_schema: Dict[str, Any],
    input_data: Dict[str, Any],
    max_credits: Optional[float] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a new agent job inside an existing task.

    Args:
        task_id: The ID of the parent task
        agent_id: The agent to run
        input_schema: The agent's input schema (from get_agent_input_schema)
        input_data: Input data for the agent
        max_credits: Maximum credits willing to pay
        name: Optional job name
    """
    body: Dict[str, Any] = {
        "agentId": agent_id,
        "inputSchema": input_schema,
        "inputData": input_data or {},
    }
    if max_credits is not None and max_credits > 0:
        body["maxCredits"] = max_credits
    if name:
        body["name"] = name
    return await _api_request("POST", f"/v1/tasks/{task_id}/jobs", body=body)


@mcp.tool()
async def list_task_events(task_id: str) -> Dict[str, Any]:
    """
    Lists events (status changes, comments) for a task.

    Args:
        task_id: The ID of the task
    """
    return await _api_request("GET", f"/v1/tasks/{task_id}/events")


@mcp.tool()
async def create_task_event(
    task_id: str,
    status: Optional[str] = None,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates an event on a task - either a status update, a comment, or both.
    At least one of status or comment must be provided.

    Args:
        task_id: The ID of the task
        status: New task status (e.g. 'IN_PROGRESS', 'COMPLETED')
        comment: Comment text
    """
    body: Dict[str, Any] = {}
    if status:
        body["status"] = status
    if comment:
        body["comment"] = comment
    if not body:
        return {"error": "At least one of status or comment must be provided"}
    return await _api_request("POST", f"/v1/tasks/{task_id}/events", body=body)


# ============================================================================
# Coworker tools (agent marketplace management)
# ============================================================================

@mcp.tool()
async def list_coworkers(
    scope: Optional[str] = None,
    capability: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lists coworkers (agent identities) available to the authenticated user.

    Args:
        scope: Optional visibility scope filter (e.g. 'public', 'organization')
        capability: Optional capability filter (e.g. 'chat', 'task'). For
            multiple capabilities, pass a comma-separated string.
    """
    params: Dict[str, Any] = {}
    if scope:
        params["scope"] = scope
    if capability:
        # Support comma-separated for multiple values
        caps = [c.strip() for c in capability.split(",") if c.strip()]
        if caps:
            params["capability"] = caps
    return await _api_request("GET", "/v1/coworkers", params=params or None)


@mcp.tool()
async def get_coworker(coworker_id: str) -> Dict[str, Any]:
    """
    Retrieves a coworker by ID.

    Args:
        coworker_id: The ID of the coworker
    """
    return await _api_request("GET", f"/v1/coworkers/{coworker_id}")


@mcp.tool()
async def get_current_coworker() -> Dict[str, Any]:
    """
    Retrieves the coworker identity associated with the current auth token.
    Only works when authenticated with a coworker API key.
    """
    return await _api_request("GET", "/v1/coworkers/me")


@mcp.tool()
async def create_coworker(
    name: str,
    caption: Optional[str] = None,
    company: Optional[str] = None,
    company_logo: Optional[str] = None,
    url: Optional[str] = None,
    base_url: Optional[str] = None,
    description: Optional[str] = None,
    image: Optional[str] = None,
    capabilities: Optional[list] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Creates a new coworker (a discoverable agent identity).

    Args:
        name: Display name (required)
        caption: Short tagline
        company: Company name
        company_logo: URL to company logo
        url: Public website URL
        base_url: Agent API base URL
        description: Long-form description
        image: Avatar image URL
        capabilities: List of capability tags (e.g. ['chat', 'task'])
        priority: Integer priority for ranking in lists
        metadata: Arbitrary key/value metadata
    """
    body: Dict[str, Any] = {"name": name}
    if caption is not None: body["caption"] = caption
    if company is not None: body["company"] = company
    if company_logo is not None: body["companyLogo"] = company_logo
    if url is not None: body["url"] = url
    if base_url is not None: body["baseURL"] = base_url
    if description is not None: body["description"] = description
    if image is not None: body["image"] = image
    if capabilities is not None: body["capabilities"] = capabilities
    if priority is not None: body["priority"] = priority
    if metadata is not None: body["metadata"] = metadata
    return await _api_request("POST", "/v1/coworkers", body=body)


@mcp.tool()
async def update_coworker(
    coworker_id: str,
    name: Optional[str] = None,
    caption: Optional[str] = None,
    company: Optional[str] = None,
    company_logo: Optional[str] = None,
    url: Optional[str] = None,
    base_url: Optional[str] = None,
    description: Optional[str] = None,
    image: Optional[str] = None,
    capabilities: Optional[list] = None,
    priority: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Updates a coworker. Only provided fields are changed.

    Args:
        coworker_id: The ID of the coworker to update
        (other args: see create_coworker)
    """
    body: Dict[str, Any] = {}
    if name is not None: body["name"] = name
    if caption is not None: body["caption"] = caption
    if company is not None: body["company"] = company
    if company_logo is not None: body["companyLogo"] = company_logo
    if url is not None: body["url"] = url
    if base_url is not None: body["baseURL"] = base_url
    if description is not None: body["description"] = description
    if image is not None: body["image"] = image
    if capabilities is not None: body["capabilities"] = capabilities
    if priority is not None: body["priority"] = priority
    if metadata is not None: body["metadata"] = metadata
    return await _api_request("PATCH", f"/v1/coworkers/{coworker_id}", body=body)


@mcp.tool()
async def create_coworker_api_key(
    coworker_id: str,
    name: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates an API key for a coworker. The raw key is returned ONCE in the
    response and cannot be retrieved later.

    Args:
        coworker_id: The ID of the coworker
        name: Optional label for the key
        expires_at: Optional ISO 8601 timestamp when the key should expire
    """
    body: Dict[str, Any] = {}
    if name is not None: body["name"] = name
    if expires_at is not None: body["expiresAt"] = expires_at
    return await _api_request(
        "POST", f"/v1/coworkers/{coworker_id}/api-keys", body=body
    )


# ============================================================================
# Category tools
# ============================================================================

@mcp.tool()
async def list_categories() -> Dict[str, Any]:
    """
    Lists all agent categories available on the platform.
    Useful for discovering agents by category.
    """
    return await _api_request("GET", "/v1/categories")


@mcp.tool()
async def get_category(category_id_or_slug: str) -> Dict[str, Any]:
    """
    Retrieves a category by its ID or slug.

    Args:
        category_id_or_slug: The category ID or URL slug
    """
    return await _api_request("GET", f"/v1/categories/{category_id_or_slug}")

# ChatGPT Compatibility Tools
# These tools are required for ChatGPT Connectors and deep research functionality

import asyncio as _asyncio
import json as _json


def _chatgpt_error(message: str) -> Dict[str, Any]:
    """Wrap an error in the ChatGPT content array format."""
    return {"content": [{"type": "text", "text": _json.dumps({"error": message})}]}


def _chatgpt_ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": _json.dumps(payload)}]}


def _agent_base_url(network: str) -> str:
    return "https://app.sokosumi.com" if network == "mainnet" else "https://preprod.sokosumi.com"


@mcp.tool()
async def search(query: str) -> Dict[str, Any]:
    """
    Search for relevant Sokosumi AI agents based on a query.

    This tool is required for ChatGPT compatibility and returns search results
    in the format expected by ChatGPT Connectors.

    Args:
        query: The search query string

    Returns:
        MCP content array with JSON-encoded search results containing:
        - results: Array of result objects with id, title, and url
    """
    result = await _api_request("GET", "/v1/agents")
    if "error" in result:
        return _chatgpt_error(result.get("error", "Failed to list agents"))

    agents = result.get("data", []) or []
    query_lower = query.lower()
    filtered = [
        a for a in agents
        if query_lower in (
            f"{a.get('name', '')} {a.get('description', '')} "
            f"{' '.join(a.get('tags', []) or [])}"
        ).lower()
    ] or agents  # fallback: all agents if nothing matches

    network = normalize_network(current_network.get() or _default_network())
    base_agent_url = _agent_base_url(network)

    results = [
        {
            "id": a.get("id", ""),
            "title": f"{a.get('name', 'Unnamed Agent')} - {a.get('price', 0)} credits",
            "url": f"{base_agent_url}/agents/{a.get('id', '')}",
        }
        for a in filtered[:20]
    ]
    logger.info(f"Search for '{query}' returned {len(results)} results")
    return _chatgpt_ok({"results": results})


@mcp.tool()
async def fetch(id: str) -> Dict[str, Any]:
    """
    Fetch detailed information about a specific Sokosumi AI agent.

    This tool is required for ChatGPT compatibility and returns full document
    content in the format expected by ChatGPT Connectors.

    Args:
        id: The unique identifier of the agent to fetch
    """
    # Run both API calls concurrently - this was the biggest win: previously
    # the list fetch blocked the schema fetch.
    agents_task = _api_request("GET", "/v1/agents")
    schema_task = _api_request("GET", f"/v1/agents/{id}/input-schema")
    agents_result, schema_result = await _asyncio.gather(agents_task, schema_task)

    if "error" in agents_result:
        return _chatgpt_error(
            f"Failed to fetch agent details: {agents_result.get('error')}"
        )

    agent = next(
        (a for a in agents_result.get("data", []) or [] if a.get("id") == id),
        None,
    )
    if not agent:
        return _chatgpt_error(f"Agent with id '{id}' not found")

    input_schema = (
        schema_result.get("data", {}) if "error" not in schema_result else {}
    )

    network = normalize_network(current_network.get() or _default_network())
    base_agent_url = _agent_base_url(network)

    text_parts = [
        f"Agent: {agent.get('name', 'Unnamed Agent')}",
        f"Description: {agent.get('description', 'No description available')}",
        f"Price: {agent.get('price', 0)} credits",
        f"Status: {agent.get('status', 'unknown')}",
    ]
    if agent.get("tags"):
        text_parts.append(f"Tags: {', '.join(agent['tags'])}")
    if input_schema:
        text_parts.append("\nInput Schema:")
        text_parts.append(_json.dumps(input_schema, indent=2))
    text_parts.extend([
        "\nTo use this agent:",
        f"1. Get input schema: get_agent_input_schema('{id}')",
        f"2. Create job: create_job(agent_id='{id}', input_schema=<schema>, "
        f"input_data={{...}}, max_credits={agent.get('price', 100)})",
        "3. Monitor job: get_job(job_id)",
    ])

    result = {
        "id": id,
        "title": f"{agent.get('name', 'Unnamed Agent')} - {agent.get('price', 0)} credits",
        "text": "\n".join(text_parts),
        "url": f"{base_agent_url}/agents/{id}",
        "metadata": {
            "source": "sokosumi_api",
            "network": network,
            "agent_status": agent.get("status", "unknown"),
            "price_credits": agent.get("price", 0),
            "tags": agent.get("tags", []),
            "has_input_schema": bool(input_schema),
        },
    }
    logger.info(f"Successfully fetched agent details for {id}")
    return _chatgpt_ok(result)


# ============================================================================
# OAuth 2.1 Endpoint Handlers (Thin Better Auth Resource Server)
# ============================================================================

def _request_network(request: Request) -> str:
    """Resolve the requested network from the query string."""
    return normalize_network(request.query_params.get("network"))


def _copy_upstream_headers(response: httpx.Response) -> Dict[str, str]:
    """Copy only the response headers that matter for OAuth clients."""
    headers: Dict[str, str] = {}
    for name in ("content-type", "cache-control", "www-authenticate"):
        value = response.headers.get(name)
        if value:
            headers[name] = value
    return headers


async def _proxy_oauth_request(
    method: str,
    url: str,
    *,
    body: bytes = b"",
    headers: Optional[Dict[str, str]] = None,
) -> Response:
    """Forward a request to the upstream Better Auth server."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        upstream = await client.request(
            method,
            url,
            content=body if body else None,
            headers=headers,
        )

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_copy_upstream_headers(upstream),
    )


async def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    """Serve OAuth 2.0 Protected Resource Metadata (RFC 9728)."""
    return JSONResponse(get_protected_resource_metadata(_request_network(request)))


async def oauth_authorization_server_metadata(request: Request) -> JSONResponse:
    """Serve OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
    return JSONResponse(get_authorization_server_metadata(_request_network(request)))


async def oauth_jwks(request: Request) -> Response:
    """Legacy compatibility proxy for cached clients that still hit /oauth/jwks."""
    network = _request_network(request)
    return await _proxy_oauth_request("GET", get_jwks_url(network))


async def oauth_authorize(request: Request) -> Response:
    """
    Legacy compatibility redirect for cached clients that still hit /oauth/authorize.

    New clients should discover and call Sokosumi Better Auth directly via the
    advertised authorization server metadata.
    """
    network = _request_network(request)
    query_params = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "network"
    ]
    target_url = build_proxy_url("/authorize", network)
    if query_params:
        target_url = f"{target_url}?{urlencode(query_params, doseq=True)}"

    return RedirectResponse(url=target_url, status_code=302)


async def oauth_callback(request: Request) -> Response:
    """Explain that the MCP no longer terminates OAuth callbacks locally."""
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head><title>Reconnect Sokosumi MCP</title></head>
        <body style="font-family: sans-serif; padding: 40px; text-align: center;">
            <h1>Reconnect Required</h1>
            <p>This MCP server now delegates OAuth directly to Sokosumi Better Auth.</p>
            <p>Please reconnect the Sokosumi MCP in your client and retry the authorization flow.</p>
            <p><a href="https://app.sokosumi.com">Return to Sokosumi</a></p>
        </body>
        </html>
        """,
        status_code=410,
    )


async def oauth_token(request: Request) -> Response:
    """Legacy compatibility proxy for cached clients that still hit /oauth/token."""
    network = _request_network(request)
    body = await request.body()
    headers: Dict[str, str] = {}
    content_type = request.headers.get("content-type")
    authorization = request.headers.get("authorization")
    if content_type:
        headers["content-type"] = content_type
    if authorization:
        headers["authorization"] = authorization

    return await _proxy_oauth_request(
        "POST",
        build_proxy_url("/token", network),
        body=body,
        headers=headers,
    )


def create_http_app():
    """Create the Streamable HTTP ASGI app with auth and OAuth metadata routes."""
    global _http_app
    if _http_app is not None:
        return _http_app

    app = mcp.streamable_http_app()
    oauth_routes = [
        Route(
            "/.well-known/oauth-protected-resource",
            oauth_protected_resource_metadata,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            oauth_authorization_server_metadata,
            methods=["GET"],
        ),
        Route(
            "/oauth/jwks",
            oauth_jwks,
            methods=["GET"],
        ),
        Route(
            "/oauth/authorize",
            oauth_authorize,
            methods=["GET"],
        ),
        Route(
            "/oauth/callback",
            oauth_callback,
            methods=["GET"],
        ),
        Route(
            "/oauth/token",
            oauth_token,
            methods=["POST"],
        ),
    ]
    for route in oauth_routes:
        app.routes.insert(0, route)

    app.add_middleware(AuthenticationMiddleware)
    _http_app = app
    return app


if __name__ == "__main__":
    import uvicorn

    # Check if we're running on Railway (PORT env var is set)
    port = os.environ.get("PORT")

    if port:
        # Remote deployment - use Streamable HTTP transport
        logger.info(f"Starting MCP server on port {port}")

        try:
            # Get the ASGI app from FastMCP for Streamable HTTP
            # This is the modern standard (2025-06-18 spec)
            app = create_http_app()
            logger.info("Using Streamable HTTP transport")
            logger.info("Added OAuth metadata and compatibility proxy endpoints")
            logger.info("Added authentication middleware (API key + OAuth)")

            # Run with uvicorn
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=int(port),
                log_level="info",
                access_log=True
            )
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            sys.exit(1)
    else:
        # Local development - use stdio transport
        logger.info("Starting MCP server with stdio transport for local development")
        mcp.run(transport='stdio')
