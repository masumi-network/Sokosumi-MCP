#!/usr/bin/env python
"""
Minimal MCP server with FastMCP for remote deployment.
Using Streamable HTTP transport (the modern standard).
Extracts API key and network from URL parameters using ASGI middleware.
"""

import os
import logging
import sys
from typing import Optional, Dict, Any
import httpx
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from contextvars import ContextVar

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

# Middleware to extract API key and network from URL parameters
class APIKeyExtractorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_token = None
        network_token = None
        try:
            # Extract API key from query parameters
            api_key = request.query_params.get('api_key')
            if api_key:
                # Store in context for this request
                api_token = current_api_key.set(api_key)
                # Also store globally for demo purposes
                api_keys["current"] = api_key
                logger.info(f"Extracted API key from URL: {api_key[:8]}..." if len(api_key) > 8 else "API key extracted")
            
            # Extract network from query parameters (preprod or mainnet)
            network = request.query_params.get('network', 'mainnet')  # Default to mainnet
            if network not in ['preprod', 'mainnet']:
                network = 'mainnet'  # Default to mainnet if invalid value
            # Store in context for this request
            network_token = current_network.set(network)
            # Also store globally for demo purposes
            networks["current"] = network
            logger.info(f"Using network: {network}")
            
            # Continue processing the request
            response = await call_next(request)
            
            # Clean up context if we set it
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
                
            return response
        except Exception as e:
            logger.error(f"Middleware error: {e}")
            # Don't fail the request due to middleware errors
            return await call_next(request)

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
    - Jobs typically take AT MINIMUM 7 minutes to complete
    - Some jobs may take much longer (15-30+ minutes)
    - Keep checking periodically until status shows:
      - "completed" (success - output will be available)
      - "failed" (job failed - check error details)
    - If monitoring for extended periods, consider checking manually later
    
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
    body = {
        "maxAcceptedCredits": max_accepted_credits
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
            
            # Add middleware to extract API key from URL parameters
            app.add_middleware(APIKeyExtractorMiddleware)
            logger.info("Added API key extraction middleware")
            
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