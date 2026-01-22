#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Using Streamable HTTP transport (the modern standard).
Includes self-contained OAuth 2.1 authorization server per MCP spec.
"""

import os
import logging
import sys
from typing import Optional, Dict, Any
from urllib.parse import urlencode, parse_qs
import httpx
import jwt
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, RedirectResponse, HTMLResponse
from starlette.routing import Route
from contextvars import ContextVar

from oauth import (
    validate_access_token,
    get_protected_resource_metadata,
    get_authorization_server_metadata,
    get_www_authenticate_header,
    get_jwks,
    get_login_page_html,
    create_authorization_session,
    get_authorization_session,
    create_authorization_code,
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

# Create the FastMCP server instance
mcp = FastMCP("sokosumi-mcp")

# Simple in-memory storage for demonstration
api_keys = {}
networks = {}

# Context variables to store request-specific data
current_api_key: ContextVar[Optional[str]] = ContextVar('current_api_key', default=None)
current_network: ContextVar[Optional[str]] = ContextVar('current_network', default=None)
current_user: ContextVar[Optional[Dict[str, Any]]] = ContextVar('current_user', default=None)

# Middleware for authentication (API key or OAuth Bearer token)
class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware supporting dual auth:
    1. API key (query param ?api_key= or header x-api-key)
    2. OAuth 2.1 Bearer token (Authorization: Bearer <jwt>)

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

            # Try Bearer token authentication
            bearer_token = self._extract_bearer_token(request)
            if bearer_token:
                try:
                    user_payload = await validate_access_token(bearer_token)
                    user_token = current_user.set(user_payload)

                    # Also set the API key from the JWT payload for downstream API calls
                    api_key_from_jwt = user_payload.get('api_key')
                    if api_key_from_jwt:
                        api_token = current_api_key.set(api_key_from_jwt)
                        api_keys["current"] = api_key_from_jwt

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
    if network is None:
        network = current_network.get() or networks.get('current', 'mainnet')

    if network == 'preprod':
        return 'https://preprod.sokosumi.com/api'
    else:
        return 'https://app.sokosumi.com/api'

# Helper function to get API key
def get_current_api_key() -> Optional[str]:
    """
    Get the current API key from context or storage.

    Returns:
        The API key or None if not found
    """
    return current_api_key.get() or api_keys.get('current')


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
        return {"error": "No API key found. Please connect with ?api_key=xxx in URL"}

    base_url = get_base_url()
    url = f"{base_url}/v1/agents"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"x-api-key": api_key},
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
        return {"error": "No API key found. Please connect with ?api_key=xxx in URL"}

    base_url = get_base_url()
    url = f"{base_url}/v1/agents/{agent_id}/input-schema"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"x-api-key": api_key},
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
        return {"error": "No API key found. Please connect with ?api_key=xxx in URL"}

    base_url = get_base_url()
    url = f"{base_url}/v1/agents/{agent_id}/jobs"

    # Prepare request body
    # Always request sharing within organization when creating (server may ignore if unsupported)
    body = {
        "maxAcceptedCredits": max_accepted_credits,
        "shareOrganization": True,
    }
    if input_data is not None:
        body["inputData"] = input_data
    if name is not None:
        body["name"] = name

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=body,
                headers={"x-api-key": api_key},
                timeout=30.0
            )

            if response.status_code in [200, 201]:
                data = response.json()
                logger.info(f"Successfully created job {data.get('data', {}).get('id')} for agent {agent_id}")
                return data
            else:
                logger.error(f"Failed to create job: {response.status_code} - {response.text}")
                return {
                    "error": f"Failed to create job: {response.status_code}",
                    "details": response.text
                }
    except Exception as e:
        logger.error(f"Error creating job: {str(e)}")
        return {
            "error": "Failed to connect to Sokosumi API",
            "details": str(e)
        }

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
        return {"error": "No API key found. Please connect with ?api_key=xxx in URL"}

    base_url = get_base_url()
    url = f"{base_url}/v1/jobs/{job_id}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"x-api-key": api_key},
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
        return {"error": "No API key found. Please connect with ?api_key=xxx in URL"}

    base_url = get_base_url()
    url = f"{base_url}/v1/agents/{agent_id}/jobs"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"x-api-key": api_key},
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
        return {"error": "No API key found. Please connect with ?api_key=xxx in URL"}

    base_url = get_base_url()
    url = f"{base_url}/v1/users/me"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"x-api-key": api_key},
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
                "text": json.dumps({"error": "No API key found. Please connect with ?api_key=xxx in URL"})
            }]
        }

    # Get all agents first
    base_url = get_base_url()
    url = f"{base_url}/v1/agents"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"x-api-key": api_key},
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
                "text": json.dumps({"error": "No API key found. Please connect with ?api_key=xxx in URL"})
            }]
        }

    base_url = get_base_url()

    try:
        # Get agent details and input schema in parallel
        async with httpx.AsyncClient() as client:
            # Get agent list to find specific agent
            agents_response = await client.get(
                f"{base_url}/v1/agents",
                headers={"x-api-key": api_key},
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
                headers={"x-api-key": api_key},
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

    Handles the authorization request by showing a login page.
    Supports PKCE (required by MCP spec).
    """
    # Extract OAuth parameters
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

    # Create authorization session
    session_id = create_authorization_session(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        scope=scope,
        state=state,
        resource=resource,
    )

    logger.info(f"OAuth authorize: showing login page for session {session_id[:8]}...")

    # Show login page
    return HTMLResponse(content=get_login_page_html(session_id))


async def oauth_login(request: Request) -> Response:
    """
    Handle login form submission.

    Validates the API key and redirects back to the client with an auth code.
    """
    # Parse form data
    form = await request.form()
    session_id = form.get("session_id", "")
    api_key = form.get("api_key", "")

    if not session_id or not api_key:
        return HTMLResponse(
            content=get_login_page_html(session_id, error="Please enter your API key"),
            status_code=400,
        )

    # Get session
    session = get_authorization_session(session_id)
    if not session:
        return HTMLResponse(
            content=get_login_page_html(session_id, error="Session expired. Please try again."),
            status_code=400,
        )

    # Validate API key by calling Sokosumi API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://app.sokosumi.com/api/v1/users/me",
                headers={"x-api-key": api_key},
                timeout=10.0,
            )

            if response.status_code != 200:
                logger.warning(f"Invalid API key: {response.status_code}")
                return HTMLResponse(
                    content=get_login_page_html(session_id, error="Invalid API key. Please check and try again."),
                    status_code=400,
                )

            user_data = response.json().get("data", {})
            user_id = user_data.get("id", "unknown")

    except Exception as e:
        logger.error(f"Error validating API key: {e}")
        return HTMLResponse(
            content=get_login_page_html(session_id, error="Could not validate API key. Please try again."),
            status_code=500,
        )

    # Create authorization code
    try:
        code = create_authorization_code(session_id, user_id, api_key)
    except ValueError as e:
        return HTMLResponse(
            content=get_login_page_html(session_id, error=str(e)),
            status_code=400,
        )

    # Redirect back to client with authorization code
    redirect_params = {
        "code": code,
        "state": session["state"],
    }

    redirect_url = f"{session['redirect_uri']}?{urlencode(redirect_params)}"
    logger.info(f"OAuth login successful, redirecting to: {redirect_url[:50]}...")

    return RedirectResponse(url=redirect_url, status_code=302)


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
            tokens = refresh_access_token(refresh_token)
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
                    "/oauth/login",
                    oauth_login,
                    methods=["POST"],
                ),
                Route(
                    "/oauth/token",
                    oauth_token,
                    methods=["POST"],
                ),
            ]
            for route in oauth_routes:
                app.routes.insert(0, route)
            logger.info("Added OAuth 2.1 endpoints (self-contained authorization server)")

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
