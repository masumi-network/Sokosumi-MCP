# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server for the Sokosumi AI agent platform. The server provides tools to interact with Sokosumi's AI agents, create jobs, and monitor execution. Built with FastMCP using the modern MCP specification and supports dual transport modes.

**Key Architecture Pattern**: This implements a **dual-transport MCP server**:
- **Local Development**: STDIO transport for Claude Desktop integration
- **Remote Deployment**: Streamable HTTP transport for cloud platforms (Railway, Cloud Run)

## Development Commands

### Environment Setup
```bash
# Initial setup
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Copy environment template (optional for local testing)
cp .env.example .env
```

### Running the Server
```bash
# Local development (STDIO mode for Claude Desktop)
source venv/bin/activate
python server.py

# Test the server locally
python test_client.py
```

### Testing
```bash
# Test remote deployment
chmod +x test_remote.sh
./test_remote.sh https://your-server-url.com your-api-key

# Local testing with environment variables
SOKOSUMI_API_KEY=your_key SOKOSUMI_NETWORK=mainnet python server.py
```

### Deployment
```bash
# Deploy to Railway (automatic via git push)
railway up --detach

# Check deployment status
railway status
railway logs
```

## Core Architecture

### Transport Detection Pattern
The server automatically detects deployment mode:
```python
port = os.environ.get("PORT")
if port:
    # Remote deployment - Streamable HTTP
    app = mcp.streamable_http_app()
    app.add_middleware(APIKeyExtractorMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=int(port))
else:
    # Local development - STDIO
    mcp.run(transport='stdio')
```

### API Key Management
Uses ASGI middleware to extract credentials from URL parameters:
- API keys: `?api_key=xxx` 
- Network selection: `?network=mainnet` or `?network=preprod`
- Context variables store request-scoped authentication data

### Sokosumi API Integration
Base URLs are network-dependent:
- **Mainnet**: `https://app.sokosumi.com/api`
- **Preprod**: `https://preprod.sokosumi.com/api`

All API calls use async httpx with:
- `x-api-key` header authentication
- 30-second timeout
- Comprehensive error handling and logging

## MCP Tools Structure

The server provides 8 tools total - 6 core Sokosumi tools plus 2 ChatGPT compatibility tools:

### Core Sokosumi Tools
1. **`list_agents()`** - Browse available AI agents with pricing
2. **`get_agent_input_schema(agent_id)`** - Get required parameters before job creation
3. **`create_job(agent_id, max_accepted_credits, input_data, name)`** - Submit new jobs
4. **`get_job(job_id)`** - Monitor job status and retrieve results
5. **`list_agent_jobs(agent_id)`** - List jobs for specific agents
6. **`get_user_profile()`** - Get account information

### ChatGPT Compatibility Tools
7. **`search(query)`** - Search for agents by query (required for ChatGPT Connectors)
8. **`fetch(id)`** - Fetch detailed agent information by ID (required for ChatGPT Connectors)

### Recommended Workflow Pattern
```python
# 1. Get schema first
schema = await get_agent_input_schema("agent-id")

# 2. Create job with validated input
job = await create_job(
    agent_id="agent-id",
    max_accepted_credits=100,
    input_data=validated_data,  # Must match schema
    name="optional-job-name"
)

# 3. Wait before first status check (minimum 3 minutes)
# DO NOT check immediately - agents need time to initialize

# 4. Monitor until completion (minimum 7+ minutes total)
while True:
    status = await get_job(job["data"]["id"])
    if status["data"]["status"] in ["completed", "failed"]:
        break
    # For long-running jobs, save job_id and check back later
```

## File Structure

- **`server.py`** - Main FastMCP server with dual transport support
- **`test_client.py`** - STDIO transport test client
- **`test_remote.sh`** - HTTP transport test script
- **`requirements.txt`** - Python dependencies (mcp>=1.2.0, uvicorn>=0.30.0, starlette>=0.37.0, httpx>=0.25.0)
- **`railway.json`** - Railway deployment configuration
- **`Procfile`** - Railway start command
- **`.env.example`** - Environment variable template

## Claude Desktop Integration

Add to Claude Desktop MCP configuration:

**Local Development:**
```json
{
  "mcpServers": {
    "sokosumi": {
      "command": "python",
      "args": ["/absolute/path/to/Sokosumi-MCP/server.py"],
      "env": {
        "SOKOSUMI_API_KEY": "your-api-key-here",
        "SOKOSUMI_NETWORK": "mainnet"
      }
    }
  }
}
```

**Remote Server (via mcp-remote bridge):**
```json
{
  "mcpServers": {
    "sokosumi": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://your-server.up.railway.app/mcp?api_key=YOUR_API_KEY&network=mainnet"
      ]
    }
  }
}
```

## ChatGPT Integration

The server is compatible with ChatGPT Connectors and deep research features through two additional tools:

### Search Tool
- **Purpose**: Enables ChatGPT to search for relevant agents
- **Usage**: `search(query)` - searches agent names, descriptions, and tags
- **Returns**: JSON-encoded results with `id`, `title`, and `url` for each agent
- **Format**: MCP content array with `type: "text"` and JSON string payload

### Fetch Tool  
- **Purpose**: Enables ChatGPT to retrieve detailed agent information
- **Usage**: `fetch(id)` - gets full agent details including input schema
- **Returns**: JSON-encoded document with `id`, `title`, `text`, `url`, and `metadata`
- **Content**: Includes comprehensive agent details, pricing, usage instructions

### ChatGPT Connector Setup
To use with ChatGPT:
1. Deploy the server to a public endpoint (Railway, Cloud Run, etc.)
2. Add to ChatGPT as a custom connector with your server URL
3. Include API key in URL: `https://your-server.com?api_key=xxx&network=mainnet`

## Important Constraints

### Job Processing Times
- **Wait before first check**: Minimum 3 minutes after job creation
- **Total minimum runtime**: 7 minutes per job
- **Typical runtime**: 15-30+ minutes (many jobs take longer)
- **Status checking**: Poll `get_job()` every 5-10 minutes, not continuously
- **Long-running jobs**: Save job_id and check back later rather than waiting
- **Status values**: `pending`, `running`, `completed`, `failed`

### API Authentication
- Production: API keys via URL parameters (`?api_key=xxx`)
- Local testing: Environment variables or .env file
- Get API keys from: https://app.sokosumi.com/account

### Network Selection
- **mainnet**: Production environment (default)
- **preprod**: Testing environment
- Affects base URL and available agents

## Resources and Prompts

The server includes built-in MCP resources and prompts:

- **Resource**: `masumi://input-schema-standard` - MIP-003 specification for understanding agent input schemas
- **Prompt**: `hire_agent` - Step-by-step workflow guide for hiring agents

Use these for context when working with agent schemas or job creation workflows.
