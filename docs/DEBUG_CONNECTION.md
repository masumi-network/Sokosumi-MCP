## Common Issues and Solutions

### 1. Server Shows "Disconnected" in Claude Desktop

#### Check 1: Verify Server is Running
Run the test script with your Railway URL:
```bash
chmod +x test_remote.sh
./test_remote.sh https://your-app.up.railway.app your-api-key
```

Expected responses:
- HTTP Status should be 200 or 405
- You should see JSON-RPC responses
- Tools should be listed correctly

#### Check 2: Correct Connection Method
For **remote servers** (Railway, Cloud Run, etc.):
1. Open Claude Desktop
2. Go to **Settings** → **Connectors** → **Custom Connector**
3. Enter your server URL: `https://your-app.up.railway.app?api_key=YOUR_KEY`
4. Click "Connect"

❌ **DO NOT** add remote servers via `claude_desktop_config.json` - that's only for local servers!

#### Check 3: Transport Protocol
Make sure your server is using the correct transport:
- **Streamable HTTP** (preferred, modern standard)
- **SSE** (fallback for older clients)

Our server tries Streamable HTTP first, then falls back to SSE.

#### Check 4: Middleware Issues
The middleware might be interfering with MCP protocol. If tests fail, try:

1. **Test without middleware first:**
```python
# Comment out this line in server.py:
# app.add_middleware(APIKeyExtractorMiddleware)
```

2. **Add better error handling:**
```python
class APIKeyExtractorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            api_key = request.query_params.get('api_key')
            if api_key:
                api_keys["current"] = api_key
                logger.info(f"Extracted API key: {api_key[:8]}...")
        except Exception as e:
            logger.error(f"Middleware error: {e}")
        
        response = await call_next(request)
        return response
```

### 2. Railway-Specific Issues

#### Check Railway Logs
```bash
railway logs
```

Look for:
- Server startup messages
- Connection attempts from Claude
- Any error messages

#### Verify Environment Variables
```bash
railway variables
```

Ensure `PORT` is set (Railway sets this automatically).

#### Check Deployment Status
```bash
railway status
```

### 3. Testing MCP Protocol Compliance

Test the core MCP methods:

```bash
# Initialize
curl -X POST https://your-app.up.railway.app \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"1.0.0"}}'

# List tools
curl -X POST https://your-app.up.railway.app \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Call a tool
curl -X POST https://your-app.up.railway.app \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"test_connection","arguments":{}}}'
```

### 4. Alternative Implementation (No Middleware)

If middleware continues to cause issues, extract API key differently:

```python
@mcp.tool()
def set_api_key_from_env() -> str:
    """
    Set API key from environment variable.
    Set RAILWAY_API_KEY in Railway dashboard.
    """
    api_key = os.environ.get("RAILWAY_API_KEY")
    if api_key:
        api_keys["current"] = api_key
        return f"API key set from environment: {api_key[:4]}..."
    return "No API key found in environment"
```

Then in Railway dashboard, set:
```
RAILWAY_API_KEY=your-actual-api-key
```

### 5. Debug Checklist

- [ ] Server is deployed and running (check Railway dashboard)
- [ ] Server responds to HTTP requests (test with curl)
- [ ] Using Settings → Connectors in Claude Desktop (not JSON config)
- [ ] URL format is correct: `https://your-app.up.railway.app`
- [ ] If using API key in URL: `https://your-app.up.railway.app?api_key=KEY`
- [ ] Server logs show incoming requests from Claude
- [ ] No CORS or authentication errors in logs
- [ ] MCP protocol methods respond correctly

### 6. Quick Fix Attempts

1. **Restart Railway deployment:**
```bash
railway restart
```

2. **Force redeploy:**
```bash
railway up --detach
```

3. **Check if server is accessible:**
```bash
curl -I https://your-app.up.railway.app
```

4. **Try without API key first:**
Connect with just the base URL to see if connection works at all.

### Need More Help?

1. Check Railway logs: `railway logs --tail`
2. Check Claude Desktop console (Developer Tools)
3. Test with the provided `test_remote.sh` script
4. Share error messages from both server and client logs