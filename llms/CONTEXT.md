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
- **Dual authentication** (MCP Authorization spec compliant):
  - **API Key**: Via `?api_key=xxx` query parameter or `x-api-key` header
  - **OAuth 2.1 Bearer Token**: Via `Authorization: Bearer <jwt>` header
  - Self-contained OAuth authorization server (no external dependencies)
  - Automatic discovery via `/.well-known/oauth-protected-resource`
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
- `server.py` - FastMCP server with Sokosumi API integration and self-contained OAuth server
- `oauth.py` - OAuth 2.1 self-contained authorization server (PKCE, JWT signing, token validation)
- `requirements.txt` - Python dependencies (mcp, uvicorn, starlette, httpx, PyJWT, cryptography)
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

### OAuth 2.1 Authentication (MCP Spec Compliant)

This MCP server implements a **self-contained OAuth 2.1 authorization server** following the [MCP Authorization specification](https://spec.modelcontextprotocol.io/specification/draft/basic/authorization/). No external OAuth provider is required.

#### How It Works

1. User initiates OAuth flow with PKCE
2. MCP server shows login page
3. User authenticates with their **Sokosumi API key**
4. MCP server validates API key against Sokosumi API
5. MCP server issues JWT access token (signed with RSA)
6. User uses JWT token for MCP requests

#### Discovery Endpoints

**Protected Resource Metadata (RFC 9728)**:
```
GET https://sokosumi-mcp-production.up.railway.app/.well-known/oauth-protected-resource
```
Returns:
```json
{
  "resource": "https://sokosumi-mcp-production.up.railway.app",
  "authorization_servers": ["https://sokosumi-mcp-production.up.railway.app"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["mcp:read", "mcp:write"]
}
```

**Authorization Server Metadata (RFC 8414)**:
```
GET https://sokosumi-mcp-production.up.railway.app/.well-known/oauth-authorization-server
```
Returns:
```json
{
  "issuer": "https://sokosumi-mcp-production.up.railway.app",
  "authorization_endpoint": "https://sokosumi-mcp-production.up.railway.app/oauth/authorize",
  "token_endpoint": "https://sokosumi-mcp-production.up.railway.app/oauth/token",
  "jwks_uri": "https://sokosumi-mcp-production.up.railway.app/oauth/jwks",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "code_challenge_methods_supported": ["S256"]
}
```

#### OAuth Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/oauth/authorize` | GET | Authorization endpoint - shows login page |
| `/oauth/login` | POST | Handles login form submission |
| `/oauth/token` | POST | Token endpoint - exchanges code for tokens |
| `/oauth/jwks` | GET | JWKS endpoint for token verification |
| `/.well-known/oauth-protected-resource` | GET | Protected Resource Metadata |
| `/.well-known/oauth-authorization-server` | GET | Authorization Server Metadata |

#### OAuth Flow (Detailed)

1. **Client initiates authorization**:
   ```
   GET /oauth/authorize?
     response_type=code&
     client_id=your-client-id&
     redirect_uri=http://localhost:3000/callback&
     code_challenge=<S256_CHALLENGE>&
     code_challenge_method=S256&
     state=<RANDOM_STATE>&
     scope=mcp:read%20mcp:write
   ```

2. **Server shows login page** - User enters their Sokosumi API key

3. **Server validates API key** against Sokosumi's `/api/v1/users/me` endpoint

4. **Server redirects with auth code**:
   ```
   302 Redirect to: http://localhost:3000/callback?code=<AUTH_CODE>&state=<STATE>
   ```

5. **Client exchanges code for tokens**:
   ```
   POST /oauth/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code&
   code=<AUTH_CODE>&
   code_verifier=<PKCE_VERIFIER>&
   client_id=your-client-id&
   redirect_uri=http://localhost:3000/callback
   ```

6. **Server returns JWT tokens**:
   ```json
   {
     "access_token": "eyJhbGciOiJSUzI1NiIs...",
     "token_type": "Bearer",
     "expires_in": 3600,
     "refresh_token": "abc123...",
     "scope": "mcp:read mcp:write"
   }
   ```

#### Authentication Priority

1. **API key** (query param `?api_key=` or `x-api-key` header) - checked first
2. **Bearer token** (`Authorization: Bearer <jwt>`) - checked if no API key
3. **Neither** - returns 401 with `WWW-Authenticate` header for discovery

#### Using OAuth Tokens

After obtaining a token, include it in your MCP requests:

```bash
# With curl
curl -X POST "https://sokosumi-mcp-production.up.railway.app/mcp" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# With mcp-remote (OAuth tokens via header)
npx mcp-remote "https://sokosumi-mcp-production.up.railway.app/mcp" \
  --header "Authorization: Bearer YOUR_JWT_TOKEN"
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

Note: The MCP server now always includes `shareOrganization: true` in the request body when creating jobs. The Sokosumi API may ignore this flag if unsupported, but it will be sent by default for compatibility with newer endpoints.

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
| Authentication | ✅ API key + OAuth 2.1 Bearer | ✅ Complete |
| OAuth Server | ✅ Self-contained (PKCE, JWT) | ✅ Complete |
| OAuth Discovery | ✅ RFC 9728 + RFC 8414 | ✅ Complete |
| JWT Signing | ✅ RSA 2048 (auto-generated keys) | ✅ Complete |
| Session Management | ⚠️ In-memory | Redis or database |
| Parameter Extraction | ✅ API key & network from URL | ✅ Complete |
| Error Handling | ✅ Comprehensive | ✅ Complete |
| Logging | ✅ stderr logging | ✅ Complete |
| CORS | ⚠️ Partial | Full CORS headers |

## Implementation Details

### OAuth 2.1 Self-Contained Authorization Server
The MCP server implements a complete OAuth 2.1 authorization server:
- **RSA Key Generation**: 2048-bit RSA keys generated on startup (can be persisted via env vars)
- **PKCE Support**: S256 code challenge method (required by MCP spec)
- **JWT Tokens**: RS256 signed access tokens with configurable expiry
- **Refresh Tokens**: Token rotation for security
- **JWKS Endpoint**: Public keys for token verification

### Authentication Middleware
- **API Key**: Extracts from `?api_key=xxx` query param or `x-api-key` header
- **OAuth Bearer**: Validates JWT from `Authorization: Bearer <jwt>` header
- JWT validated locally using server's own public key
- Returns 401 with `WWW-Authenticate` header pointing to discovery endpoint if unauthenticated
- Stores auth info in context variables for request-scoped access

### Key Files
- **`oauth.py`**: Self-contained OAuth module with:
  - RSA key generation and management
  - JWKS generation
  - OAuth session management
  - Authorization code generation
  - Token exchange with PKCE validation
  - JWT token creation and validation
  - Login page HTML generation

### Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | HTTP port (triggers remote mode) | None (uses stdio) |
| `MCP_SERVER_URL` | Public URL of the server | `https://sokosumi-mcp-production.up.railway.app` |
| `OAUTH_PRIVATE_KEY` | PEM-encoded RSA private key | Auto-generated |
| `OAUTH_KEY_ID` | Key ID for JWKS | Auto-generated |

### Sokosumi API Integration
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

1. **Persistent Storage**
   - Replace in-memory dict with database
   - Add session management with Redis
   - Persist RSA keys across deployments

2. **Enhanced Features**
   - Add job status polling/monitoring
   - Implement job cancellation
   - Add batch job submission
   - Implement rate limiting per API key

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
