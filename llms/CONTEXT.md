# Sokosumi MCP Server

## Overview
MCP (Model Context Protocol) server for the Sokosumi AI agent platform. Provides tools to interact with Sokosumi's AI agents, create jobs, and monitor execution. Built with FastMCP and dual transport support (stdio for local, Streamable HTTP for remote).

## Architecture Type
This is a **Remote MCP Server** implementation, which according to industry guides represents the future direction of MCP:
- ✅ Runs on cloud platforms (Railway, Cloud Run, etc.)
- ✅ Accessible via HTTPS
- ✅ No local configuration needed for end users
- ✅ Instant updates for all users
- ✅ Centrally managed

## Key Features
- Uses official MCP Python SDK with **FastMCP**
- **Dual transport support**:
  - STDIO transport for local MCP clients (Claude Desktop, etc.)
  - Streamable HTTP transport for remote access (Railway deployment)
- **Parameter extraction from URL**: ASGI middleware automatically extracts:
  - API keys from `?api_key=xxx` query parameter
  - Network from `?network=preprod` or `?network=mainnet` (defaults to mainnet)
- **Sokosumi API Integration**: Full suite of tools for AI agent job management:
  - `list_agents()`: Browse available AI agents with pricing
  - `get_agent_input_schema(agent_id)`: Get required input parameters for an agent
  - `create_job(agent_id, max_accepted_credits, input_data, name)`: Submit a new job
  - `get_job(job_id)`: Check job status and retrieve results
  - `list_agent_jobs(agent_id)`: View jobs for a specific agent
  - `get_user_profile()`: Get your account information
- **Resources**:
  - `masumi://input-schema-standard`: Masumi Input Schema Standard (MIP-003) documentation
- **Prompts**:
  - `hire_agent`: Step-by-step guide for hiring agents (get schema → create job → monitor status)

## Deployment Modes

### 1. Railway/Cloud Run (HTTP) - Production
When deployed with PORT env var set, uses Streamable HTTP transport:
- **Endpoint**: `https://sokosumi-mcp-production.up.railway.app/mcp` (Streamable HTTP endpoint)
- **Transport**: Streamable HTTP (the modern standard)
- **Protocol**: MCP 2025-06-18 specification
- **Access**: Remote MCP clients via HTTP

### 2. Local Development (STDIO)
When run locally without PORT env var:
- **Transport**: Standard Input/Output
- **Access**: Local MCP clients like Claude Desktop
- **Use Case**: Development and testing

## Files
- `server.py` - FastMCP server with Sokosumi API integration
- `requirements.txt` - Python dependencies (mcp>=1.2.0, uvicorn>=0.30.0, starlette>=0.37.0, httpx>=0.25.0)
- `railway.json` - Railway deployment configuration
- `Procfile` - Railway start command
- `test_client.py` - Test client for stdio transport
- `CONTEXT.md` - This documentation file

## How to Connect

### Using mcp-remote Bridge with API Key
Until clients support remote servers directly:
```json
{
  "mcpServers": {
    "sokosumi": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://sokosumi-mcp-production.up.railway.app/mcp?api_key=YOUR_API_KEY&network=mainnet"
      ]
    }
  }
}
```

### Direct Remote Connection with API Key (Future)
When clients support remote MCP servers:
```
https://sokosumi-mcp-production.up.railway.app/mcp?api_key=YOUR_API_KEY&network=mainnet
```

The API key and network will be automatically extracted from the URL and made available to all tools.

### Local Development
```json
{
  "mcpServers": {
    "sokosumi-local": {
      "command": "python",
      "args": ["/path/to/server.py"]
    }
  }
}
```

## Available Tools

### 1. `list_agents()`
Lists all available AI agents with:
- Agent ID, name, and description
- Pricing in credits (including fees)
- Status and availability
- Tags for categorization

### 2. `get_agent_input_schema(agent_id)`
Gets the required input schema for a specific agent before creating a job.

### 3. `create_job(agent_id, max_accepted_credits, input_data, name)`
Creates a new job for an agent:
- `agent_id`: The agent to use
- `max_accepted_credits`: Maximum credits you're willing to pay
- `input_data`: Input parameters (must match agent's schema)
- `name`: Optional job name for tracking

### 4. `get_job(job_id)`
Retrieves a specific job's status and results:
- Current status (pending, running, completed, failed)
- Output data (when completed)
- Execution timestamps
- Credits charged

### 5. `list_agent_jobs(agent_id)`
Lists all jobs for a specific agent.

### 6. `get_user_profile()`
Gets your account information including name, email, and preferences.

## Available Resources

### `masumi://input-schema-standard`
Provides the Masumi Input Schema Standard (MIP-003) documentation. Use this resource when:
- Understanding the expected format of agent input schemas
- Encountering issues with input validation
- Constructing proper input data for job creation

Reference: [MIP-003 Specification](https://github.com/masumi-network/masumi-improvement-proposals/blob/main/MIPs/MIP-003/MIP-003-Attachement-01.md)

## Available Prompts

### `hire_agent`
A comprehensive guide for hiring agents on Sokosumi. The recommended workflow is:

1. **Get Agent Input Schema**: Use `get_agent_input_schema(agent_id)` to understand required parameters
2. **Create Job**: Submit with `create_job()` including validated input data
3. **Monitor Status**: Poll `get_job(job_id)` until status shows completed or failed
   - **Note**: Jobs take minimum 7 minutes, often 15-30+ minutes
   - Keep checking periodically or check manually later for long-running jobs

## Testing

### Test with curl
```bash
# Initialize connection with API key and network
curl -X POST "https://sokosumi-mcp-production.up.railway.app/mcp?api_key=YOUR_KEY&network=mainnet" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    },
    "id": 1
  }'
```

### Local Testing
```bash
pip install -r requirements.txt
python server.py  # Runs as stdio server
python test_client.py  # In another terminal
```

## Current Status

| Feature | Current Status | Production Needs |
|---------|---------------|------------------|
| Transport | ✅ Streamable HTTP | ✅ Complete |
| Tools | ✅ Full Sokosumi API integration | ✅ Complete |
| Authentication | ✅ API key via header | ✅ Complete |
| Session Management | ⚠️ In-memory | Redis or database |
| Parameter Extraction | ✅ API key & network from URL | ✅ Complete |
| Error Handling | ✅ Comprehensive | ✅ Complete |
| Logging | ✅ stderr logging | ✅ Complete |
| CORS | ⚠️ Partial | Full CORS headers |

## Implementation Details
- **FastMCP**: Using the recommended FastMCP approach
- **Transport Detection**: Automatic based on PORT env var
- **Streamable HTTP**: `mcp.streamable_http_app()` creates ASGI app for modern HTTP transport
- **Uvicorn**: Production ASGI server for HTTP deployment
- **Logging**: Properly configured to stderr (not stdout)
- **Parameter Middleware**: ASGI middleware (`APIKeyExtractorMiddleware`) automatically extracts parameters from URL:
  - Intercepts incoming requests and checks for `?api_key=xxx` and `?network=preprod/mainnet`
  - Stores extracted values in context variables for request-scoped access
  - Uses Starlette's `BaseHTTPMiddleware` for request interception
- **Sokosumi API Integration**:
  - Base URLs: `https://preprod.sokosumi.com/api` (preprod) or `https://app.sokosumi.com/api` (mainnet)
  - Authentication via `x-api-key` header
  - All API calls use async httpx client with 30s timeout
  - Comprehensive error handling and logging

## Why FastMCP?
Based on best practices and official examples:
1. **Simpler API**: Decorators for tools make code cleaner
2. **Built-in Transport**: Handles Streamable HTTP/SSE/stdio automatically
3. **Production Ready**: Used in Google's official examples
4. **Type Safety**: Better IDE support and type hints

## Next Steps for Production

1. **Add OAuth 2.1 Authentication**
   - Implement `/.well-known/oauth-protected-resource`
   - Add `/authorize`, `/token` endpoints
   - Implement PKCE flow

2. **Persistent Storage**
   - Replace in-memory dict with database
   - Add session management with Redis

3. **Enhanced Features**
   - Add job status polling/monitoring
   - Implement job cancellation
   - Add batch job submission
   - Implement rate limiting per API key

4. **Monitoring**
   - Add health checks
   - Implement metrics
   - Set up alerting

## References
- [Sokosumi Platform](https://app.sokosumi.com)
- [MCP Specification](https://modelcontextprotocol.org)
- [FastMCP Documentation](https://github.com/modelcontextprotocol/python-sdk)
- [Google Cloud Run MCP Tutorial](https://cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server)