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
- **OAuth 2.1 Authentication** (MCP Authorization spec compliant):
  - Delegates authentication to Sokosumi's OAuth provider
  - Users login with their Sokosumi account (no API key needed)
  - Automatic discovery via `/.well-known/oauth-protected-resource`
  - Also supports direct API key authentication for backwards compatibility
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
- **Endpoint**: `https://mcp.sokosumi.com/mcp` (Streamable HTTP endpoint)
- **Transport**: Streamable HTTP (the modern standard)
- **Protocol**: MCP 2025-06-18 specification
- **Access**: Remote MCP clients via HTTP

### 2. Local Development (STDIO)
When run locally without PORT env var:
- **Transport**: Standard Input/Output
- **Access**: Local MCP clients like Claude Desktop
- **Use Case**: Development and testing

## Files
- `server.py` - FastMCP server with Sokosumi API integration and OAuth routes
- `oauth.py` - OAuth 2.1 client (delegates to Sokosumi) + server (issues JWTs to MCP clients)
- `requirements.txt` - Python dependencies (mcp, uvicorn, starlette, httpx, PyJWT, cryptography)
- `railway.json` - Railway deployment configuration
- `Procfile` - Railway start command
- `test_client.py` - Test client for stdio transport
- `llms/CONTEXT.md` - This documentation file

## How to Connect

### Using mcp-remote Bridge (Recommended - OAuth Flow)
Until clients support remote servers directly:
```json
{
  "mcpServers": {
    "sokosumi": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://mcp.sokosumi.com/mcp"
      ]
    }
  }
}
```

When you connect, mcp-remote will:
1. Discover OAuth endpoints via `/.well-known/oauth-authorization-server`
2. Open your browser to Sokosumi's login page
3. You login with your Sokosumi account credentials
4. Get redirected back and authenticated automatically

### Using mcp-remote with API Key (Legacy)
For backwards compatibility, you can still use API keys:
```json
{
  "mcpServers": {
    "sokosumi": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://mcp.sokosumi.com/mcp?api_key=YOUR_API_KEY&network=mainnet"
      ]
    }
  }
}
```

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

## OAuth 2.1 Authentication Flow

This MCP server implements OAuth 2.1 that **delegates to Sokosumi's OAuth provider**. Users login with their Sokosumi account, not API keys.

### How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  mcp-remote │     │  MCP Server │     │   Sokosumi  │
│   (client)  │     │             │     │    OAuth    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       │ 1. /oauth/authorize                   │
       │──────────────────>│                   │
       │                   │                   │
       │ 2. Redirect to Sokosumi               │
       │<──────────────────│                   │
       │                   │                   │
       │ 3. User logs in   │                   │
       │───────────────────────────────────────>
       │                   │                   │
       │ 4. Callback with code                 │
       │<──────────────────────────────────────│
       │                   │                   │
       │ 5. /oauth/callback (code)             │
       │──────────────────>│                   │
       │                   │                   │
       │                   │ 6. Exchange code  │
       │                   │──────────────────>│
       │                   │                   │
       │                   │ 7. Sokosumi token │
       │                   │<──────────────────│
       │                   │                   │
       │ 8. Redirect with MCP code             │
       │<──────────────────│                   │
       │                   │                   │
       │ 9. /oauth/token   │                   │
       │──────────────────>│                   │
       │                   │                   │
       │ 10. MCP JWT token │                   │
       │<──────────────────│                   │
       │                   │                   │
       │ 11. /mcp (with JWT)                   │
       │──────────────────>│                   │
       │                   │                   │
```

### Discovery Endpoints

**Protected Resource Metadata (RFC 9728)**:
```
GET https://mcp.sokosumi.com/.well-known/oauth-protected-resource
```
Returns:
```json
{
  "resource": "https://mcp.sokosumi.com",
  "authorization_servers": ["https://mcp.sokosumi.com"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["mcp:read", "mcp:write"]
}
```

**Authorization Server Metadata (RFC 8414)**:
```
GET https://mcp.sokosumi.com/.well-known/oauth-authorization-server
```
Returns:
```json
{
  "issuer": "https://mcp.sokosumi.com",
  "authorization_endpoint": "https://mcp.sokosumi.com/oauth/authorize",
  "token_endpoint": "https://mcp.sokosumi.com/oauth/token",
  "jwks_uri": "https://mcp.sokosumi.com/oauth/jwks",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"]
}
```

### OAuth Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/oauth/authorize` | GET | Redirects to Sokosumi OAuth for login |
| `/oauth/callback` | GET | Receives callback from Sokosumi after login |
| `/oauth/token` | POST | Exchanges MCP auth code for JWT token |
| `/oauth/jwks` | GET | JWKS endpoint for token verification |
| `/.well-known/oauth-protected-resource` | GET | Protected Resource Metadata |
| `/.well-known/oauth-authorization-server` | GET | Authorization Server Metadata |

### Authentication Priority

1. **API key** (query param `?api_key=` or `x-api-key` header) - checked first
2. **Bearer token** (`Authorization: Bearer <jwt>`) - checked if no API key
3. **Neither** - returns 401 with `WWW-Authenticate` header for discovery

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

Note: The MCP server always includes `shareOrganization: true` in the request body when creating jobs.

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
# Initialize connection (will return 401 prompting OAuth)
curl -X POST "https://mcp.sokosumi.com/mcp" \
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

# With API key (legacy)
curl -X POST "https://mcp.sokosumi.com/mcp?api_key=YOUR_KEY&network=mainnet" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
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
| Authentication | ✅ API key + OAuth 2.1 Bearer | ✅ Complete |
| OAuth Flow | ✅ Delegates to Sokosumi OAuth | ✅ Complete |
| JWT Signing | ✅ RSA 2048 (auto-generated keys) | ✅ Complete |
| Session Management | ⚠️ In-memory | Redis or database |
| Parameter Extraction | ✅ API key & network from URL | ✅ Complete |
| Error Handling | ✅ Comprehensive | ✅ Complete |
| Logging | ✅ stderr logging | ✅ Complete |
| CORS | ⚠️ Partial | Full CORS headers |

## Implementation Details

### OAuth 2.1 Architecture
The MCP server implements a hybrid OAuth architecture:

**As OAuth Client (to Sokosumi)**:
- Redirects users to Sokosumi's `/auth/oauth2/authorize`
- Exchanges Sokosumi auth codes for Sokosumi access tokens
- Uses Sokosumi tokens for API calls

**As OAuth Server (to MCP clients)**:
- Issues its own JWTs to mcp-remote clients
- Signs tokens with RSA 2048-bit keys
- Provides JWKS endpoint for verification

### Authentication Middleware
- **API Key**: Extracts from `?api_key=xxx` query param or `x-api-key` header
- **OAuth Bearer**: Validates JWT from `Authorization: Bearer <jwt>` header
- Automatically uses appropriate auth for Sokosumi API (Bearer or x-api-key)
- Returns 401 with `WWW-Authenticate` header if unauthenticated

### Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | HTTP port (triggers remote mode) | None (uses stdio) |
| `MCP_SERVER_URL` | Public URL of the server | `https://mcp.sokosumi.com` |
| `SOKOSUMI_OAUTH_BASE_URL` | Sokosumi OAuth base URL | `https://app.sokosumi.com` |
| `OAUTH_CLIENT_ID` | OAuth client ID for Sokosumi | Required for OAuth |
| `OAUTH_CLIENT_SECRET` | OAuth client secret for Sokosumi | Required for OAuth |
| `OAUTH_PRIVATE_KEY` | PEM-encoded RSA private key | Auto-generated |
| `OAUTH_KEY_ID` | Key ID for JWKS | Auto-generated |

### Sokosumi API Integration
- Base URLs: `https://preprod.sokosumi.com/api` (preprod) or `https://app.sokosumi.com/api` (mainnet)
- Authentication: Bearer token (OAuth) or x-api-key header (API key)
- All API calls use async httpx client with 30s timeout
- Comprehensive error handling and logging

## Why FastMCP?
Based on best practices and official examples:
1. **Simpler API**: Decorators for tools make code cleaner
2. **Built-in Transport**: Handles Streamable HTTP/SSE/stdio automatically
3. **Production Ready**: Used in Google's official examples
4. **Type Safety**: Better IDE support and type hints

## Next Steps for Production

1. **Persistent Storage**
   - Replace in-memory dict with database
   - Add session management with Redis
   - Persist RSA keys across deployments

2. **Enhanced Features**
   - Add job status polling/monitoring
   - Implement job cancellation
   - Add batch job submission
   - Implement rate limiting per user

3. **Monitoring**
   - Add health checks
   - Implement metrics
   - Set up alerting

## References
- [Sokosumi Platform](https://app.sokosumi.com)
- [MCP Specification](https://modelcontextprotocol.org)
- [MCP Authorization Spec](https://spec.modelcontextprotocol.io/specification/draft/basic/authorization/)
- [FastMCP Documentation](https://github.com/modelcontextprotocol/python-sdk)
- [Google Cloud Run MCP Tutorial](https://cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server)
