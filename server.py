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
from urllib.parse import urlencode, parse_qs
import httpx
import jwt
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, RedirectResponse, HTMLResponse
from starlette.routing import Route
from contextvars import ContextVar

from oauth import (
    MCP_SERVER_URL,
    SOKOSUMI_USERINFO_ENDPOINT,
    validate_access_token,
    get_protected_resource_metadata,
    get_authorization_server_metadata,
    get_www_authenticate_header,
    get_jwks,
    create_mcp_session,
    get_mcp_session,
    build_sokosumi_auth_url,
    exchange_sokosumi_code,
    create_mcp_auth_code,
    exchange_code_for_tokens,
    refresh_access_token,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

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

# Simple in-memory storage for demonstration
api_keys = {}
networks = {}

# Context variables to store request-specific data
current_api_key: ContextVar[Optional[str]] = ContextVar('current_api_key', default=None)
current_network: ContextVar[Optional[str]] = ContextVar('current_network', default=None)
current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar('current_user', default=None)

# Middleware for authentication (API key, direct Bearer token, or OAuth Bearer JWT)
class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware supporting dual auth:
    1. API key (query param ?api_key= or header x-api-key/token)
    2. Direct Sokosumi token (Authorization: Bearer <api key or access token>)
    3. OAuth 2.1 Bearer token (Authorization: Bearer <jwt>)

    Priority: explicit API key takes precedence over Bearer token.
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
            network = request.query_params.get('network', 'mainnet')
            if network not in ['preprod', 'mainnet']:
                network = 'mainnet'
            network_token = current_network.set(network)
            networks["current"] = network
            logger.info(f"Using network: {network}")

            # Try API key authentication first
            api_key = self._extract_api_key(request)
            if api_key:
                api_token = current_api_key.set(api_key)
                api_keys["current"] = api_key
                logger.info(f"Authenticated via API key: {api_key[:8]}..." if len(api_key) > 8 else "API key auth")
                response = await call_next(request)
                return self._cleanup_and_return(response, api_token, network_token, user_token)

            # Try Bearer token authentication. MCP OAuth tokens are JWTs issued
            # by this server. Other bearer values, including Sokosumi tokens that
            # happen to use JWT format, are passed through as direct Sokosumi
            # API/OAuth tokens for clients that only expose a Bearer token field.
            bearer_token = self._extract_bearer_token(request)
            if bearer_token:
                if not self._is_mcp_access_token(bearer_token):
                    if not await self._validate_sokosumi_bearer_token(bearer_token, network):
                        logger.warning("Invalid direct Bearer token")
                        return self._unauthorized_response("Invalid bearer token")

                    api_token = current_api_key.set(bearer_token)
                    api_keys["current"] = bearer_token
                    logger.info(
                        "Authenticated via direct Bearer token: %s...",
                        bearer_token[:8],
                    )
                    response = await call_next(request)
                    return self._cleanup_and_return(response, api_token, network_token, user_token)

                try:
                    user_payload = await validate_access_token(bearer_token)
                    user_token = current_user.set(user_payload)

                    # Extract Sokosumi token from JWT payload for downstream API calls
                    # This is the Sokosumi OAuth access token obtained during authentication
                    sokosumi_token = user_payload.get('sokosumi_token')
                    if sokosumi_token:
                        # Store the Sokosumi token as the "API key" for downstream calls
                        # The Sokosumi API accepts Bearer tokens as well
                        api_token = current_api_key.set(sokosumi_token)
                        api_keys["current"] = sokosumi_token

                    logger.info(f"Authenticated via JWT for user: {user_payload.get('sub', 'unknown')}")
                    response = await call_next(request)
                    return self._cleanup_and_return(response, api_token, network_token, user_token)
                except jwt.InvalidTokenError as e:
                    logger.warning(f"Invalid JWT token: {e}")
                    return self._unauthorized_response("Invalid or expired token")
                except Exception as e:
                    logger.error(f"JWT validation error: {e}")
                    return self._unauthorized_response("Token validation failed")

            # No valid authentication - return 401
            # Only require auth for /mcp endpoint, allow other endpoints through
            if request.url.path.startswith("/mcp"):
                return self._unauthorized_response("Authentication required")

            # Allow non-MCP endpoints through (health checks, etc.)
            response = await call_next(request)
            return self._cleanup_and_return(response, api_token, network_token, user_token)

        except Exception as e:
            logger.error(f"Middleware error: {e}")
            return await call_next(request)

    def _extract_api_key(self, request: Request) -> Optional[str]:
        """Extract API key from query param or header."""
        # Check query parameter first. `api_key` is the documented legacy
        # remote URL form; the aliases accept older/generated variants safely.
        api_key = (
            request.query_params.get('api_key')
            or request.query_params.get('apiKey')
            or request.query_params.get('token')
            or request.query_params.get('access_token')
        )
        if api_key:
            return api_key

        # Check API key headers
        api_key = request.headers.get('x-api-key') or request.headers.get('token')
        if api_key:
            return api_key

        return None

    def _extract_bearer_token(self, request: Request) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        auth_header = request.headers.get('authorization', '')
        if auth_header.lower().startswith('bearer '):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None

    def _is_mcp_access_token(self, token: str) -> bool:
        """Return true only for JWTs issued by this MCP server."""
        if token.count(".") != 2:
            return False

        try:
            payload = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except jwt.InvalidTokenError:
            return False

        audience = payload.get("aud")
        has_expected_audience = (
            audience == MCP_SERVER_URL
            or (isinstance(audience, list) and MCP_SERVER_URL in audience)
        )
        return payload.get("iss") == MCP_SERVER_URL and has_expected_audience

    async def _validate_sokosumi_bearer_token(self, token: str, network: str) -> bool:
        """Validate a direct Sokosumi bearer token before allowing MCP access."""
        base_url = get_base_url(network)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                for path in ("/v1/users/me", "/v1/coworkers/me"):
                    response = await client.get(
                        f"{base_url}{path}",
                        headers=headers,
                        timeout=10.0,
                    )
                    if 200 <= response.status_code < 300:
                        return True
                    if response.status_code not in (401, 403):
                        logger.warning(
                            "Unexpected Sokosumi bearer validation response: %s %s",
                            path,
                            response.status_code,
                        )
        except httpx.HTTPError as e:
            logger.warning("Sokosumi bearer validation failed: %s", e)

        return False

    def _unauthorized_response(self, detail: str) -> Response:
        """Return a 401 Unauthorized response with WWW-Authenticate header."""
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "detail": detail},
            headers={"WWW-Authenticate": get_www_authenticate_header()},
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
    explicit_base_url = os.environ.get("SOKOSUMI_API_BASE_URL")
    if explicit_base_url:
        return explicit_base_url.rstrip("/")

    if network is None:
        network = (
            current_network.get()
            or networks.get('current')
            or os.environ.get("SOKOSUMI_NETWORK")
            or 'mainnet'
        )

    if network == 'preprod':
        return os.environ.get(
            "SOKOSUMI_PREPROD_API_BASE_URL",
            "https://api.preprod.sokosumi.com",
        ).rstrip("/")
    else:
        return os.environ.get(
            "SOKOSUMI_MAINNET_API_BASE_URL",
            "https://api.sokosumi.com",
        ).rstrip("/")

# Helper function to get API key/token
def get_current_api_key() -> Optional[str]:
    """
    Get the current API key or OAuth token from context or storage.

    Returns:
        The API key/token or None if not found
    """
    return (
        current_api_key.get()
        or api_keys.get('current')
        or os.environ.get("SOKOSUMI_API_KEY")
        or os.environ.get("SOKOSUMI_AUTH_TOKEN")
        or os.environ.get("API_KEY")
    )


def get_auth_headers() -> Dict[str, str]:
    """
    Get authentication headers for Sokosumi API calls.

    Returns headers using Bearer authentication. Sokosumi CLI uses the same
    header for user API keys, user OAuth tokens, and coworker bearer tokens.
    """
    token = get_current_api_key()
    if not token:
        return {}

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def auth_error() -> Dict[str, Any]:
    """Return a consistent authentication error for MCP tools."""
    return {
        "error": "No Sokosumi authentication found",
        "details": (
            "Connect the Sokosumi MCP server with OAuth, pass ?api_key=... "
            "for local HTTP development, or set SOKOSUMI_API_KEY for stdio."
        ),
    }


async def sokosumi_api_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Call the Sokosumi API and return a JSON-compatible response."""
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    base_url = get_base_url()
    url = f"{base_url}/{path.lstrip('/')}"

    clean_params = {
        key: value
        for key, value in (params or {}).items()
        if value is not None and value != "" and value != []
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method.upper(),
                url,
                params=clean_params or None,
                json=json_body,
                headers=get_auth_headers(),
                timeout=timeout,
            )

        if 200 <= response.status_code < 300:
            if not response.text:
                return {"data": None}
            try:
                return response.json()
            except Exception:
                return {"data": response.text}

        logger.error(
            "Sokosumi API request failed: %s %s -> %s - %s",
            method.upper(),
            url,
            response.status_code,
            response.text,
        )
        return {
            "error": f"Sokosumi API request failed: {response.status_code}",
            "details": response.text,
            "path": path,
        }
    except Exception as e:
        logger.error("Sokosumi API request error: %s %s - %s", method, url, e)
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e),
            "path": path,
        }


def _data_items(response: Dict[str, Any]) -> list:
    """Extract list data from a Sokosumi API envelope."""
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, list) else []


async def resolve_coworker(reference: str, scope: str = "whitelisted") -> Optional[Dict[str, Any]]:
    """Resolve a coworker by id, slug, or name."""
    if not reference:
        return None

    needle = reference.strip().lower()
    if not needle:
        return None

    if needle.startswith("cow_"):
        response = await sokosumi_api_request("GET", f"/v1/coworkers/{reference.strip()}")
        data = response.get("data") if isinstance(response, dict) else None
        return data if isinstance(data, dict) else None

    for candidate_scope in [scope, "all"]:
        response = await sokosumi_api_request(
            "GET",
            "/v1/coworkers",
            params={"scope": candidate_scope},
        )
        if response.get("error"):
            continue

        coworkers = _data_items(response)
        exact = next(
            (
                coworker
                for coworker in coworkers
                if needle
                in {
                    str(coworker.get("id", "")).lower(),
                    str(coworker.get("slug", "")).lower(),
                    str(coworker.get("name", "")).lower(),
                }
            ),
            None,
        )
        if exact:
            return exact

        partial = next(
            (
                coworker
                for coworker in coworkers
                if needle in str(coworker.get("name", "")).lower()
                or needle in str(coworker.get("slug", "")).lower()
            ),
            None,
        )
        if partial:
            return partial

    return None


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Get the current authenticated user from JWT context.

    Returns:
        The user payload dict or None if not authenticated via JWT
    """
    return current_user.get()


def is_authenticated() -> bool:
    """
    Check if the current request is authenticated (via API key or JWT).

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

    Returns:
        A dictionary containing the list of available agents with their details:
        - id: Agent identifier
        - name: Agent name
        - description: Agent description
        - status: Agent status
        - price: Credits required (including fee)
        - tags: Associated tags
        - isNew: Whether the agent is new
        - isShown: Whether the agent is shown
    """
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    base_url = get_base_url()
    url = f"{base_url}/v1/agents"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=get_auth_headers(),
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved {len(data.get('data', []))} agents")
                return data
            else:
                logger.error(f"Failed to list agents: {response.status_code} - {response.text}")
                return {
                    "error": f"Failed to list agents: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        logger.error(f"Error listing agents: {str(e)}")
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e)
        }

@mcp.tool()
async def get_agent_input_schema(agent_id: str) -> Dict[str, Any]:
    """
    Gets the required input schema for a specific agent.

    Args:
        agent_id: The ID of the agent to get the input schema for

    Returns:
        The input schema for the agent, describing required parameters
    """
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    base_url = get_base_url()
    url = f"{base_url}/v1/agents/{agent_id}/input-schema"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=get_auth_headers(),
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved input schema for agent {agent_id}")
                return data
            else:
                logger.error(f"Failed to get input schema: {response.status_code} - {response.text}")
                return {
                    "error": f"Failed to get input schema: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        logger.error(f"Error getting input schema: {str(e)}")
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e)
        }


@mcp.tool()
async def get_agent(agent_id: str) -> Dict[str, Any]:
    """
    Gets details for a specific Sokosumi agent.

    Args:
        agent_id: The ID of the agent to retrieve.

    Returns:
        Agent details including name, description, pricing, status, tags, and metadata.
    """
    return await sokosumi_api_request("GET", f"/v1/agents/{agent_id}")


@mcp.tool()
async def list_categories() -> Dict[str, Any]:
    """
    Lists Sokosumi marketplace categories.

    Returns:
        Categories that can help narrow agent discovery.
    """
    return await sokosumi_api_request("GET", "/v1/categories")

@mcp.tool()
async def create_job(
    agent_id: str,
    max_accepted_credits: float,
    input_data: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a new job for a specific agent.

    Args:
        agent_id: The ID of the agent to create a job for
        max_accepted_credits: Maximum credits you're willing to pay for this job
        input_data: Input data for the agent (must match agent's input schema)
        name: Optional name for the job

    Returns:
        The created job details including job ID and status
    """
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    schema_response = await sokosumi_api_request(
        "GET",
        f"/v1/agents/{agent_id}/input-schema",
    )
    if schema_response.get("error"):
        return schema_response

    input_schema = schema_response.get("data") or {}
    body = {
        "inputSchema": input_schema,
        "inputData": input_data or {},
        "maxCredits": max_accepted_credits,
    }
    if name is not None:
        body["name"] = name

    data = await sokosumi_api_request(
        "POST",
        f"/v1/agents/{agent_id}/jobs",
        json_body=body,
    )
    if not data.get("error"):
        logger.info(f"Successfully created job for agent {agent_id}")
    return data

@mcp.tool()
async def get_job(job_id: str) -> Dict[str, Any]:
    """
    Retrieves status and results for a specific job.

    Args:
        job_id: The ID of the job to retrieve

    Returns:
        Job details including:
        - status: Current job status
        - output: Job output (if completed)
        - input: Original input data
        - price: Credits charged
        - timestamps: Various job lifecycle timestamps
    """
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    base_url = get_base_url()
    url = f"{base_url}/v1/jobs/{job_id}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=get_auth_headers(),
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved job {job_id}")
                return data
            else:
                logger.error(f"Failed to get job: {response.status_code} - {response.text}")
                return {
                    "error": f"Failed to get job: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        logger.error(f"Error getting job: {str(e)}")
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e)
        }


@mcp.tool()
async def list_agent_jobs(agent_id: str) -> Dict[str, Any]:
    """
    Lists all jobs for a specific agent belonging to the authenticated user.

    Args:
        agent_id: The ID of the agent to list jobs for

    Returns:
        List of jobs for the specified agent with full job details
    """
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    base_url = get_base_url()
    url = f"{base_url}/v1/agents/{agent_id}/jobs"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=get_auth_headers(),
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved {len(data.get('data', []))} jobs for agent {agent_id}")
                return data
            else:
                logger.error(f"Failed to list agent jobs: {response.status_code} - {response.text}")
                return {
                    "error": f"Failed to list agent jobs: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        logger.error(f"Error listing agent jobs: {str(e)}")
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e)
        }

@mcp.tool()
async def get_user_profile() -> Dict[str, Any]:
    """
    Gets the current user's profile information.

    Returns:
        User profile including:
        - id: User identifier
        - name: User's name
        - email: User's email
        - termsAccepted: Terms acceptance status
        - marketingOptIn: Marketing preference
        - timestamps: Account creation/update times
    """
    api_key = get_current_api_key()
    if not api_key:
        return auth_error()

    base_url = get_base_url()
    url = f"{base_url}/v1/users/me"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=get_auth_headers(),
                timeout=30.0
            )

            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved user profile")
                return data
            else:
                logger.error(f"Failed to get user profile: {response.status_code} - {response.text}")
                return {
                    "error": f"Failed to get user profile: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}")
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e)
        }


@mcp.tool()
async def list_coworkers(
    scope: str = "whitelisted",
    capability: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Lists Sokosumi coworkers for multi-agent task workflows.

    Args:
        scope: Coworker visibility scope: whitelisted, all, or archived.
        capability: Optional capability filter such as chat or tasks.
        search: Optional local search across coworker id, slug, name, company, caption, and description.
        limit: Optional maximum number of coworkers to return.

    Returns:
        A Sokosumi API response containing coworker records.
    """
    if scope not in ["whitelisted", "all", "archived"]:
        return {"error": "Invalid scope", "details": "Use whitelisted, all, or archived"}

    response = await sokosumi_api_request(
        "GET",
        "/v1/coworkers",
        params={"scope": scope, "capability": capability},
    )
    if response.get("error"):
        return response

    coworkers = _data_items(response)
    if search:
        needle = search.strip().lower()
        coworkers = [
            coworker
            for coworker in coworkers
            if needle
            in " ".join(
                str(coworker.get(field, "") or "")
                for field in ["id", "slug", "name", "company", "caption", "description"]
            ).lower()
        ]

    if limit is not None and limit > 0:
        coworkers = coworkers[:limit]

    return {**response, "data": coworkers}


@mcp.tool()
async def get_coworker(coworker: str) -> Dict[str, Any]:
    """
    Gets a coworker by id, slug, or name.

    Args:
        coworker: Coworker id, slug, or name, for example "hannah" or "elena".

    Returns:
        A Sokosumi API response containing the resolved coworker.
    """
    resolved = await resolve_coworker(coworker)
    if not resolved:
        return {
            "error": "Coworker not found",
            "details": f"No coworker matched {coworker!r}",
        }
    return {"data": resolved}


@mcp.tool()
async def create_coworker_task(
    coworker: str,
    description: str,
    name: Optional[str] = None,
    status: str = "READY",
) -> Dict[str, Any]:
    """
    Creates a Sokosumi task assigned to a coworker such as Hannah or Elena.

    Args:
        coworker: Coworker id, slug, or name.
        description: The work brief for the coworker.
        name: Optional task name. If omitted, a short name is derived from the description.
        status: DRAFT to stage the task, or READY to start it immediately.

    Returns:
        The created task response.
    """
    if status not in ["DRAFT", "READY"]:
        return {"error": "Invalid status", "details": "Use DRAFT or READY"}
    if not description or not description.strip():
        return {"error": "description is required"}

    resolved = await resolve_coworker(coworker)
    if not resolved:
        return {
            "error": "Coworker not found",
            "details": f"No coworker matched {coworker!r}",
        }

    task_name = name or description.strip().splitlines()[0][:120] or "New Task"
    body = {
        "name": task_name,
        "description": description,
        "coworkerId": resolved.get("id"),
        "status": status,
        "origin": "SOKOSUMI",
    }
    return await sokosumi_api_request("POST", "/v1/tasks", json_body=body)


@mcp.tool()
async def list_tasks(
    q: Optional[str] = None,
    status: Optional[str] = None,
    scope: str = "owned",
    coworker: Optional[str] = None,
    coworker_id: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lists Sokosumi tasks in the active workspace.

    Args:
        q: Optional case-insensitive task name search.
        status: Optional comma-separated status filter, for example READY,RUNNING.
        scope: owned or workspace.
        coworker: Optional coworker id, slug, or name to resolve as a filter.
        coworker_id: Optional coworker id filter.
        limit: Number of tasks to return.
        cursor: Optional pagination cursor.

    Returns:
        A paginated Sokosumi API task list response.
    """
    if scope not in ["owned", "workspace"]:
        return {"error": "Invalid scope", "details": "Use owned or workspace"}

    resolved_coworker_id = coworker_id
    if coworker and not coworker_id:
        resolved = await resolve_coworker(coworker)
        if not resolved:
            return {
                "error": "Coworker not found",
                "details": f"No coworker matched {coworker!r}",
            }
        resolved_coworker_id = resolved.get("id")

    return await sokosumi_api_request(
        "GET",
        "/v1/tasks",
        params={
            "q": q,
            "status": status,
            "scope": scope,
            "coworkerId": resolved_coworker_id,
            "limit": limit,
            "cursor": cursor,
        },
    )


@mcp.tool()
async def get_task(task_id: str) -> Dict[str, Any]:
    """
    Retrieves details for a Sokosumi task.

    Args:
        task_id: The task id.

    Returns:
        A task detail response.
    """
    return await sokosumi_api_request("GET", f"/v1/tasks/{task_id}")


@mcp.tool()
async def list_task_events(task_id: str) -> Dict[str, Any]:
    """
    Lists activity events for a Sokosumi task.

    Args:
        task_id: The task id.

    Returns:
        A task events response.
    """
    return await sokosumi_api_request("GET", f"/v1/tasks/{task_id}/events")


@mcp.tool()
async def create_task_event(
    task_id: str,
    comment: Optional[str] = None,
    status: Optional[str] = None,
    credits: Optional[float] = None,
    authentication_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Adds a task comment or status event.

    Args:
        task_id: The task id.
        comment: Optional task comment.
        status: Optional task status update.
        credits: Optional credits for spendable completion/cancel events.
        authentication_url: Required when setting AUTHENTICATION_REQUIRED.

    Returns:
        The created task event response.
    """
    body: Dict[str, Any] = {"origin": "SOKOSUMI"}
    if comment is not None:
        body["comment"] = comment
    if status is not None:
        body["status"] = status
    if credits is not None:
        body["credits"] = credits
    if authentication_url is not None:
        body["authenticationUrl"] = authentication_url

    if "comment" not in body and "status" not in body:
        return {"error": "comment or status is required"}

    return await sokosumi_api_request(
        "POST",
        f"/v1/tasks/{task_id}/events",
        json_body=body,
    )


@mcp.tool()
async def list_task_jobs(task_id: str) -> Dict[str, Any]:
    """
    Lists agent jobs attached to a Sokosumi task.

    Args:
        task_id: The task id.

    Returns:
        The task jobs response.
    """
    return await sokosumi_api_request("GET", f"/v1/tasks/{task_id}/jobs")


@mcp.tool()
async def add_job_to_task(
    task_id: str,
    agent_id: str,
    max_accepted_credits: float,
    input_data: Optional[Dict[str, Any]] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Adds an agent job to an existing task.

    This endpoint is primarily for coworker bearer-token execution. If a normal
    user token is connected, the API may reject the request.

    Args:
        task_id: The task id.
        agent_id: The agent id.
        max_accepted_credits: Maximum credits to spend.
        input_data: Input data matching the agent input schema.
        name: Optional job name.

    Returns:
        The created job response.
    """
    schema_response = await sokosumi_api_request(
        "GET",
        f"/v1/agents/{agent_id}/input-schema",
    )
    if schema_response.get("error"):
        return schema_response

    body = {
        "agentId": agent_id,
        "inputSchema": schema_response.get("data") or {},
        "inputData": input_data or {},
        "maxCredits": max_accepted_credits,
    }
    if name is not None:
        body["name"] = name

    return await sokosumi_api_request(
        "POST",
        f"/v1/tasks/{task_id}/jobs",
        json_body=body,
    )


@mcp.tool()
async def list_jobs(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    scope: str = "owned",
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Lists direct Sokosumi jobs in the active workspace.

    Args:
        agent_id: Optional agent id filter.
        status: Optional job status filter.
        scope: owned or workspace.
        limit: Number of jobs to return.
        cursor: Optional pagination cursor.

    Returns:
        A paginated jobs response.
    """
    if scope not in ["owned", "workspace"]:
        return {"error": "Invalid scope", "details": "Use owned or workspace"}

    return await sokosumi_api_request(
        "GET",
        "/v1/jobs",
        params={
            "agentId": agent_id,
            "status": status,
            "scope": scope,
            "limit": limit,
            "cursor": cursor,
        },
    )


@mcp.tool()
async def list_job_events(job_id: str) -> Dict[str, Any]:
    """
    Lists lifecycle events for a Sokosumi job.

    Args:
        job_id: The job id.

    Returns:
        A job events response.
    """
    return await sokosumi_api_request("GET", f"/v1/jobs/{job_id}/events")


@mcp.tool()
async def list_job_files(job_id: str) -> Dict[str, Any]:
    """
    Lists file outputs for a Sokosumi job.

    Args:
        job_id: The job id.

    Returns:
        A job files response.
    """
    return await sokosumi_api_request("GET", f"/v1/jobs/{job_id}/files")


@mcp.tool()
async def list_job_links(job_id: str) -> Dict[str, Any]:
    """
    Lists link outputs for a Sokosumi job.

    Args:
        job_id: The job id.

    Returns:
        A job links response.
    """
    return await sokosumi_api_request("GET", f"/v1/jobs/{job_id}/links")


@mcp.tool()
async def get_job_input_request(job_id: str) -> Dict[str, Any]:
    """
    Checks whether a Sokosumi job is waiting for more user input.

    Args:
        job_id: The job id.

    Returns:
        The pending input request, if any.
    """
    return await sokosumi_api_request("GET", f"/v1/jobs/{job_id}/input-request")


@mcp.tool()
async def provide_job_input(
    job_id: str,
    event_id: str,
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Provides requested input to a Sokosumi job that is awaiting input.

    Args:
        job_id: The job id.
        event_id: The awaiting-input event id.
        input_data: Input data matching the requested input schema.

    Returns:
        The created job input response.
    """
    return await sokosumi_api_request(
        "POST",
        f"/v1/jobs/{job_id}/inputs",
        json_body={"eventId": event_id, "inputData": input_data},
    )


# ChatGPT Compatibility Tools
# These tools are required for ChatGPT Connectors and deep research functionality

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
    import json

    api_key = get_current_api_key()
    if not api_key:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(auth_error())
            }]
        }

    # Get all agents first
    base_url = get_base_url()
    url = f"{base_url}/v1/agents"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=get_auth_headers(),
                timeout=30.0
            )

            if response.status_code != 200:
                logger.error(f"Failed to list agents: {response.status_code} - {response.text}")
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"error": f"Failed to list agents: {response.status_code}"})
                    }]
                }

            data = response.json()
            agents = data.get('data', [])

            # Filter agents based on query (simple text matching)
            query_lower = query.lower()
            filtered_agents = []

            for agent in agents:
                agent_text = f"{agent.get('name', '')} {agent.get('description', '')} {' '.join(agent.get('tags', []))}".lower()
                if query_lower in agent_text:
                    filtered_agents.append(agent)

            # If no matches, return all agents (fallback)
            if not filtered_agents:
                filtered_agents = agents

            # Format results for ChatGPT
            network = current_network.get() or networks.get('current', 'mainnet')
            base_agent_url = 'https://app.sokosumi.com' if network == 'mainnet' else 'https://preprod.sokosumi.com'

            results = []
            for agent in filtered_agents[:20]:  # Limit to 20 results
                results.append({
                    "id": agent.get('id', ''),
                    "title": f"{agent.get('name', 'Unnamed Agent')} - {agent.get('price', 0)} credits",
                    "url": f"{base_agent_url}/agents/{agent.get('id', '')}"
                })

            logger.info(f"Search for '{query}' returned {len(results)} results")

            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"results": results})
                }]
            }

    except Exception as e:
        logger.error(f"Error searching agents: {str(e)}")
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": f"Failed to search agents: {str(e)}"})
            }]
        }

@mcp.tool()
async def fetch(id: str) -> Dict[str, Any]:
    """
    Fetch detailed information about a specific Sokosumi AI agent.

    This tool is required for ChatGPT compatibility and returns full document
    content in the format expected by ChatGPT Connectors.

    Args:
        id: The unique identifier of the agent to fetch

    Returns:
        MCP content array with JSON-encoded document containing:
        - id: Agent identifier
        - title: Agent name and pricing
        - text: Full agent details and input schema
        - url: Link to agent page
        - metadata: Additional agent metadata
    """
    import json

    api_key = get_current_api_key()
    if not api_key:
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(auth_error())
            }]
        }

    base_url = get_base_url()

    try:
        # Get agent details and input schema in parallel
        async with httpx.AsyncClient() as client:
            # Get agent list to find specific agent
            agents_response = await client.get(
                f"{base_url}/v1/agents",
                headers=get_auth_headers(),
                timeout=30.0
            )

            if agents_response.status_code != 200:
                logger.error(f"Failed to list agents: {agents_response.status_code}")
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"error": f"Failed to fetch agent details: {agents_response.status_code}"})
                    }]
                }

            agents_data = agents_response.json()
            agents = agents_data.get('data', [])

            # Find the specific agent
            agent = None
            for a in agents:
                if a.get('id') == id:
                    agent = a
                    break

            if not agent:
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"error": f"Agent with id '{id}' not found"})
                    }]
                }

            # Get input schema
            schema_response = await client.get(
                f"{base_url}/v1/agents/{id}/input-schema",
                headers=get_auth_headers(),
                timeout=30.0
            )

            input_schema = {}
            if schema_response.status_code == 200:
                input_schema = schema_response.json().get('data', {})

            # Format full text content
            network = current_network.get() or networks.get('current', 'mainnet')
            base_agent_url = 'https://app.sokosumi.com' if network == 'mainnet' else 'https://preprod.sokosumi.com'

            # Build comprehensive text description
            text_parts = []
            text_parts.append(f"Agent: {agent.get('name', 'Unnamed Agent')}")
            text_parts.append(f"Description: {agent.get('description', 'No description available')}")
            text_parts.append(f"Price: {agent.get('price', 0)} credits")
            text_parts.append(f"Status: {agent.get('status', 'unknown')}")

            if agent.get('tags'):
                text_parts.append(f"Tags: {', '.join(agent.get('tags', []))}")

            if input_schema:
                text_parts.append("\nInput Schema:")
                text_parts.append(json.dumps(input_schema, indent=2))

            text_parts.append(f"\nTo use this agent:")
            text_parts.append(f"1. Get input schema: get_agent_input_schema('{id}')")
            text_parts.append(f"2. Create job: create_job(agent_id='{id}', max_accepted_credits={agent.get('price', 100)}, input_data={{...}})")
            text_parts.append(f"3. Monitor job: get_job(job_id)")

            full_text = "\n".join(text_parts)

            result = {
                "id": id,
                "title": f"{agent.get('name', 'Unnamed Agent')} - {agent.get('price', 0)} credits",
                "text": full_text,
                "url": f"{base_agent_url}/agents/{id}",
                "metadata": {
                    "source": "sokosumi_api",
                    "network": network,
                    "agent_status": agent.get('status', 'unknown'),
                    "price_credits": agent.get('price', 0),
                    "tags": agent.get('tags', []),
                    "has_input_schema": bool(input_schema)
                }
            }

            logger.info(f"Successfully fetched agent details for {id}")

            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result)
                }]
            }

    except Exception as e:
        logger.error(f"Error fetching agent {id}: {str(e)}")
        return {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": f"Failed to fetch agent: {str(e)}"})
            }]
        }


# ============================================================================
# OAuth 2.1 Endpoint Handlers (Self-Contained Authorization Server)
# ============================================================================

async def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    """
    Serve OAuth 2.0 Protected Resource Metadata (RFC 9728).

    This endpoint tells MCP clients where to authenticate.
    """
    return JSONResponse(get_protected_resource_metadata())


async def oauth_authorization_server_metadata(request: Request) -> JSONResponse:
    """
    Serve OAuth 2.0 Authorization Server Metadata (RFC 8414).

    This endpoint tells MCP clients the OAuth endpoints.
    """
    return JSONResponse(get_authorization_server_metadata())


async def oauth_jwks(request: Request) -> JSONResponse:
    """
    Serve the JWKS (JSON Web Key Set) for token verification.
    """
    return JSONResponse(get_jwks())


async def oauth_authorize(request: Request) -> Response:
    """
    OAuth 2.1 Authorization Endpoint.

    Redirects to Sokosumi's OAuth provider for authentication.
    Supports PKCE (required by MCP spec).
    """
    # Extract OAuth parameters from mcp-remote
    client_id = request.query_params.get("client_id", "")
    redirect_uri = request.query_params.get("redirect_uri", "")
    response_type = request.query_params.get("response_type", "")
    scope = request.query_params.get("scope", "mcp:read mcp:write")
    state = request.query_params.get("state", "")
    code_challenge = request.query_params.get("code_challenge", "")
    code_challenge_method = request.query_params.get("code_challenge_method", "")
    resource = request.query_params.get("resource")

    # Validate required parameters
    if response_type != "code":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_response_type", "error_description": "Only 'code' response type is supported"},
        )

    if not client_id:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "client_id is required"},
        )

    if not redirect_uri:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "redirect_uri is required"},
        )

    # PKCE is required per MCP spec
    if not code_challenge:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "code_challenge is required (PKCE)"},
        )

    if code_challenge_method != "S256":
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "code_challenge_method must be S256"},
        )

    # Create MCP session to track mcp-remote's request
    mcp_session_id = create_mcp_session(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        state=state,
        resource=resource,
    )

    # Build Sokosumi OAuth URL and redirect user there
    sokosumi_auth_url = build_sokosumi_auth_url(mcp_session_id)
    logger.info(f"OAuth authorize: redirecting to Sokosumi for session {mcp_session_id[:8]}...")

    return RedirectResponse(url=sokosumi_auth_url, status_code=302)


async def oauth_callback(request: Request) -> Response:
    """
    OAuth Callback Endpoint.

    Handles the callback from Sokosumi OAuth after user authentication.
    Exchanges Sokosumi's code for tokens, then redirects back to mcp-remote.
    """
    # Extract callback parameters from Sokosumi
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    error = request.query_params.get("error", "")
    error_description = request.query_params.get("error_description", "")

    # Handle errors from Sokosumi
    if error:
        logger.error(f"Sokosumi OAuth error: {error} - {error_description}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authentication Error</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Authentication Failed</h1>
                <p>Error: {error}</p>
                <p>{error_description}</p>
                <p><a href="https://app.sokosumi.com">Return to Sokosumi</a></p>
            </body>
            </html>
            """,
            status_code=400,
        )

    if not code or not state:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "error_description": "Missing code or state"},
        )

    try:
        # Exchange Sokosumi code for tokens
        sokosumi_tokens = await exchange_sokosumi_code(code, state)
        sokosumi_access_token = sokosumi_tokens["access_token"]
        sokosumi_refresh_token = sokosumi_tokens.get("refresh_token")
        mcp_session_id = sokosumi_tokens["mcp_session_id"]

        # Get user info from Sokosumi using the access token
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                SOKOSUMI_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {sokosumi_access_token}"},
                timeout=10.0,
            )

            if user_response.status_code == 200:
                user_info = user_response.json()
                user_data = user_info.get("data", user_info) if isinstance(user_info, dict) else {}
                user_id = (
                    user_data.get("sub")
                    or user_data.get("id")
                    or user_data.get("userId")
                    or user_data.get("email")
                    or "authenticated_user"
                )
            else:
                # Fallback: extract from id_token if available
                user_id = "authenticated_user"
                logger.warning(f"Could not get user info from Sokosumi: {user_response.status_code}")

        # Get the MCP session to retrieve mcp-remote's redirect_uri and state
        mcp_session = get_mcp_session(mcp_session_id)
        if not mcp_session:
            # Session might have been consumed, try to get from stored data
            raise ValueError("MCP session expired or not found")

        # Create MCP auth code for mcp-remote
        mcp_code = create_mcp_auth_code(
            mcp_session_id,
            sokosumi_access_token,
            user_id,
            sokosumi_refresh_token=sokosumi_refresh_token,
        )

        # Redirect back to mcp-remote with MCP's auth code
        redirect_params = {
            "code": mcp_code,
            "state": mcp_session["state"],
        }

        redirect_url = f"{mcp_session['redirect_uri']}?{urlencode(redirect_params)}"
        logger.info(f"OAuth callback successful, redirecting to mcp-remote: {redirect_url[:50]}...")

        return RedirectResponse(url=redirect_url, status_code=302)

    except ValueError as e:
        logger.error(f"OAuth callback error: {e}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authentication Error</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Authentication Failed</h1>
                <p>{str(e)}</p>
                <p>Please try connecting again.</p>
                <p><a href="https://app.sokosumi.com">Return to Sokosumi</a></p>
            </body>
            </html>
            """,
            status_code=400,
        )
    except Exception as e:
        logger.error(f"OAuth callback unexpected error: {e}")
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authentication Error</title></head>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>Authentication Failed</h1>
                <p>An unexpected error occurred. Please try again.</p>
                <p><a href="https://app.sokosumi.com">Return to Sokosumi</a></p>
            </body>
            </html>
            """,
            status_code=500,
        )


async def oauth_token(request: Request) -> Response:
    """
    OAuth 2.1 Token Endpoint.

    Exchanges authorization code for access token, or refreshes tokens.
    """
    # Parse form data
    form = await request.form()
    grant_type = form.get("grant_type", "")

    if grant_type == "authorization_code":
        code = form.get("code", "")
        code_verifier = form.get("code_verifier", "")
        client_id = form.get("client_id", "")
        redirect_uri = form.get("redirect_uri", "")

        if not code or not code_verifier or not client_id or not redirect_uri:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_request", "error_description": "Missing required parameters"},
            )

        try:
            tokens = exchange_code_for_tokens(code, code_verifier, client_id, redirect_uri)
            logger.info(f"Token exchange successful for client: {client_id}")
            return JSONResponse(tokens)
        except ValueError as e:
            logger.warning(f"Token exchange failed: {e}")
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_grant", "error_description": str(e)},
            )

    elif grant_type == "refresh_token":
        refresh_token = form.get("refresh_token", "")

        if not refresh_token:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_request", "error_description": "refresh_token is required"},
            )

        try:
            tokens = await refresh_access_token(refresh_token)
            logger.info("Token refresh successful")
            return JSONResponse(tokens)
        except ValueError as e:
            logger.warning(f"Token refresh failed: {e}")
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_grant", "error_description": str(e)},
            )

    else:
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type", "error_description": "Supported: authorization_code, refresh_token"},
        )


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
            app = mcp.streamable_http_app()
            logger.info("Using Streamable HTTP transport")

            # Add OAuth endpoints
            oauth_routes = [
                # Well-known endpoints
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
                # OAuth endpoints
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
            logger.info("Added OAuth 2.1 endpoints (delegating to Sokosumi OAuth)")

            # Add authentication middleware (API key or OAuth Bearer token)
            app.add_middleware(AuthenticationMiddleware)
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
