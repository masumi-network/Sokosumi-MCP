"""
OAuth 2.1 Self-Contained Authorization Server for Sokosumi MCP Server.

This module implements a complete OAuth 2.1 authorization server that:
- Generates and manages RSA keys for JWT signing
- Serves JWKS endpoint for token verification
- Implements authorization flow with PKCE
- Issues JWT access tokens
- Validates tokens for MCP requests

Per MCP spec, the authorization server can be hosted with the resource server.
"""

import os
import time
import secrets
import hashlib
import base64
import logging
import json
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

# Server URLs - use environment variable or default
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "https://sokosumi-mcp-production.up.railway.app")

# RSA Key Management
_private_key = None
_public_key = None
_key_id = None

# OAuth session storage (state -> session data)
_oauth_sessions: Dict[str, Dict[str, Any]] = {}

# Authorization code storage (code -> session data)
_auth_codes: Dict[str, Dict[str, Any]] = {}

# Refresh token storage (token -> session data)
_refresh_tokens: Dict[str, Dict[str, Any]] = {}

# Token settings
ACCESS_TOKEN_EXPIRY = 3600  # 1 hour
REFRESH_TOKEN_EXPIRY = 86400 * 30  # 30 days
AUTH_CODE_EXPIRY = 600  # 10 minutes


def _generate_rsa_keys() -> Tuple[Any, Any, str]:
    """Generate RSA key pair for JWT signing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_key = private_key.public_key()
    key_id = secrets.token_urlsafe(16)

    logger.info(f"Generated new RSA key pair with kid: {key_id}")
    return private_key, public_key, key_id


def _load_or_generate_keys():
    """Load keys from environment or generate new ones."""
    global _private_key, _public_key, _key_id

    # Check if keys are provided via environment
    private_key_pem = os.environ.get("OAUTH_PRIVATE_KEY")

    if private_key_pem:
        try:
            _private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None,
                backend=default_backend()
            )
            _public_key = _private_key.public_key()
            _key_id = os.environ.get("OAUTH_KEY_ID", secrets.token_urlsafe(16))
            logger.info(f"Loaded RSA keys from environment with kid: {_key_id}")
            return
        except Exception as e:
            logger.warning(f"Failed to load keys from environment: {e}, generating new keys")

    # Generate new keys
    _private_key, _public_key, _key_id = _generate_rsa_keys()


def get_keys():
    """Get the current RSA key pair, initializing if needed."""
    global _private_key, _public_key, _key_id

    if _private_key is None:
        _load_or_generate_keys()

    return _private_key, _public_key, _key_id


def get_jwks() -> Dict[str, Any]:
    """
    Get the JWKS (JSON Web Key Set) containing our public key.

    Returns:
        JWKS document with public key for JWT verification
    """
    _, public_key, key_id = get_keys()

    # Get public key numbers
    public_numbers = public_key.public_numbers()

    # Convert to base64url encoding
    def int_to_base64url(n: int, length: int) -> str:
        data = n.to_bytes(length, byteorder='big')
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

    # RSA 2048 has 256 byte modulus
    n = int_to_base64url(public_numbers.n, 256)
    e = int_to_base64url(public_numbers.e, 3)

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": key_id,
                "n": n,
                "e": e,
            }
        ]
    }


def get_protected_resource_metadata() -> Dict[str, Any]:
    """
    Get the OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Served at /.well-known/oauth-protected-resource
    """
    return {
        "resource": MCP_SERVER_URL,
        "authorization_servers": [MCP_SERVER_URL],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp:read", "mcp:write"],
    }


def get_authorization_server_metadata() -> Dict[str, Any]:
    """
    Get the OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Served at /.well-known/oauth-authorization-server
    """
    return {
        "issuer": MCP_SERVER_URL,
        "authorization_endpoint": f"{MCP_SERVER_URL}/oauth/authorize",
        "token_endpoint": f"{MCP_SERVER_URL}/oauth/token",
        "jwks_uri": f"{MCP_SERVER_URL}/oauth/jwks",
        "registration_endpoint": None,
        "scopes_supported": ["mcp:read", "mcp:write"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
    }


def get_www_authenticate_header(scope: Optional[str] = None) -> str:
    """
    Get the WWW-Authenticate header value for 401 responses.
    """
    resource_metadata_url = f"{MCP_SERVER_URL}/.well-known/oauth-protected-resource"
    header = f'Bearer resource_metadata="{resource_metadata_url}"'
    if scope:
        header += f', scope="{scope}"'
    return header


# PKCE helpers
def generate_code_verifier() -> str:
    """Generate a cryptographically random code verifier for PKCE."""
    return secrets.token_urlsafe(64)[:128]


def generate_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def verify_code_challenge(verifier: str, challenge: str) -> bool:
    """Verify that the code verifier matches the challenge."""
    expected = generate_code_challenge(verifier)
    return secrets.compare_digest(expected, challenge)


def generate_state() -> str:
    """Generate a random state parameter."""
    return secrets.token_urlsafe(32)


def create_authorization_session(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    state: str,
    resource: Optional[str] = None,
) -> str:
    """
    Create a new OAuth authorization session.

    Returns:
        Internal session ID for tracking
    """
    session_id = secrets.token_urlsafe(32)

    _oauth_sessions[session_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
        "state": state,
        "resource": resource,
        "created_at": time.time(),
    }

    # Clean up old sessions
    _cleanup_expired_sessions()

    logger.info(f"Created OAuth session: {session_id[:8]}...")
    return session_id


def get_authorization_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get an authorization session by ID."""
    session = _oauth_sessions.get(session_id)
    if not session:
        return None

    # Check expiry (10 minutes)
    if time.time() - session["created_at"] > AUTH_CODE_EXPIRY:
        del _oauth_sessions[session_id]
        return None

    return session


def create_authorization_code(session_id: str, user_id: str, api_key: str) -> str:
    """
    Create an authorization code after successful user authentication.

    Args:
        session_id: The authorization session ID
        user_id: The authenticated user's ID
        api_key: The user's API key (used for subsequent API calls)

    Returns:
        Authorization code
    """
    session = _oauth_sessions.pop(session_id, None)
    if not session:
        raise ValueError("Invalid session")

    code = secrets.token_urlsafe(32)

    _auth_codes[code] = {
        **session,
        "user_id": user_id,
        "api_key": api_key,
        "code_created_at": time.time(),
    }

    logger.info(f"Created authorization code for user: {user_id}")
    return code


def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    """
    Exchange an authorization code for access and refresh tokens.

    Args:
        code: The authorization code
        code_verifier: The PKCE code verifier
        client_id: The client ID
        redirect_uri: The redirect URI

    Returns:
        Token response with access_token, refresh_token, etc.

    Raises:
        ValueError: If validation fails
    """
    auth_data = _auth_codes.pop(code, None)
    if not auth_data:
        raise ValueError("Invalid authorization code")

    # Check code expiry
    if time.time() - auth_data["code_created_at"] > AUTH_CODE_EXPIRY:
        raise ValueError("Authorization code expired")

    # Verify client_id
    if auth_data["client_id"] != client_id:
        raise ValueError("Client ID mismatch")

    # Verify redirect_uri
    if auth_data["redirect_uri"] != redirect_uri:
        raise ValueError("Redirect URI mismatch")

    # Verify PKCE
    if auth_data["code_challenge_method"] != "S256":
        raise ValueError("Unsupported code challenge method")

    if not verify_code_challenge(code_verifier, auth_data["code_challenge"]):
        raise ValueError("Invalid code verifier")

    # Generate tokens
    access_token = _create_access_token(
        user_id=auth_data["user_id"],
        api_key=auth_data["api_key"],
        scope=auth_data["scope"],
        client_id=client_id,
    )

    refresh_token = _create_refresh_token(
        user_id=auth_data["user_id"],
        api_key=auth_data["api_key"],
        scope=auth_data["scope"],
        client_id=client_id,
    )

    logger.info(f"Exchanged code for tokens for user: {auth_data['user_id']}")

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRY,
        "refresh_token": refresh_token,
        "scope": auth_data["scope"],
    }


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """
    Use a refresh token to get a new access token.

    Args:
        refresh_token: The refresh token

    Returns:
        Token response with new access_token

    Raises:
        ValueError: If refresh token is invalid or expired
    """
    token_data = _refresh_tokens.get(refresh_token)
    if not token_data:
        raise ValueError("Invalid refresh token")

    # Check expiry
    if time.time() - token_data["created_at"] > REFRESH_TOKEN_EXPIRY:
        del _refresh_tokens[refresh_token]
        raise ValueError("Refresh token expired")

    # Generate new access token
    access_token = _create_access_token(
        user_id=token_data["user_id"],
        api_key=token_data["api_key"],
        scope=token_data["scope"],
        client_id=token_data["client_id"],
    )

    # Rotate refresh token
    del _refresh_tokens[refresh_token]
    new_refresh_token = _create_refresh_token(
        user_id=token_data["user_id"],
        api_key=token_data["api_key"],
        scope=token_data["scope"],
        client_id=token_data["client_id"],
    )

    logger.info(f"Refreshed tokens for user: {token_data['user_id']}")

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRY,
        "refresh_token": new_refresh_token,
        "scope": token_data["scope"],
    }


def _create_access_token(
    user_id: str,
    api_key: str,
    scope: str,
    client_id: str,
) -> str:
    """Create a signed JWT access token."""
    private_key, _, key_id = get_keys()

    now = datetime.now(timezone.utc)

    payload = {
        "iss": MCP_SERVER_URL,
        "sub": user_id,
        "aud": MCP_SERVER_URL,
        "exp": now + timedelta(seconds=ACCESS_TOKEN_EXPIRY),
        "iat": now,
        "nbf": now,
        "jti": secrets.token_urlsafe(16),
        "scope": scope,
        "client_id": client_id,
        "api_key": api_key,  # Include API key for downstream API calls
    }

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _create_refresh_token(
    user_id: str,
    api_key: str,
    scope: str,
    client_id: str,
) -> str:
    """Create a refresh token and store it."""
    token = secrets.token_urlsafe(64)

    _refresh_tokens[token] = {
        "user_id": user_id,
        "api_key": api_key,
        "scope": scope,
        "client_id": client_id,
        "created_at": time.time(),
    }

    return token


async def validate_access_token(token: str) -> Dict[str, Any]:
    """
    Validate an access token and return the payload.

    Args:
        token: The JWT access token

    Returns:
        The decoded token payload

    Raises:
        jwt.InvalidTokenError: If token is invalid
    """
    _, public_key, key_id = get_keys()

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=MCP_SERVER_URL,
            issuer=MCP_SERVER_URL,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["exp", "iat", "sub", "aud", "iss"],
            },
        )

        logger.info(f"Validated access token for user: {payload.get('sub', 'unknown')}")
        return payload

    except jwt.ExpiredSignatureError:
        logger.warning("Access token expired")
        raise
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid access token: {e}")
        raise


def _cleanup_expired_sessions():
    """Clean up expired OAuth sessions and auth codes."""
    current_time = time.time()

    # Clean sessions
    expired_sessions = [
        sid for sid, session in _oauth_sessions.items()
        if current_time - session["created_at"] > AUTH_CODE_EXPIRY
    ]
    for sid in expired_sessions:
        del _oauth_sessions[sid]

    # Clean auth codes
    expired_codes = [
        code for code, data in _auth_codes.items()
        if current_time - data["code_created_at"] > AUTH_CODE_EXPIRY
    ]
    for code in expired_codes:
        del _auth_codes[code]

    # Clean refresh tokens
    expired_refresh = [
        token for token, data in _refresh_tokens.items()
        if current_time - data["created_at"] > REFRESH_TOKEN_EXPIRY
    ]
    for token in expired_refresh:
        del _refresh_tokens[token]

    if expired_sessions or expired_codes or expired_refresh:
        logger.info(f"Cleaned up {len(expired_sessions)} sessions, {len(expired_codes)} codes, {len(expired_refresh)} refresh tokens")


def get_login_page_html(session_id: str, error: Optional[str] = None) -> str:
    """
    Generate the login page HTML.

    Args:
        session_id: The authorization session ID
        error: Optional error message to display

    Returns:
        HTML string for the login page
    """
    error_html = ""
    if error:
        error_html = f'<div class="error">{error}</div>'

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Sign in to Sokosumi MCP</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
            padding: 40px;
            width: 100%;
            max-width: 400px;
        }}
        .logo {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .logo h1 {{
            font-size: 24px;
            color: #1f2937;
            margin-bottom: 8px;
        }}
        .logo p {{
            color: #6b7280;
            font-size: 14px;
        }}
        .form-group {{
            margin-bottom: 20px;
        }}
        label {{
            display: block;
            font-size: 14px;
            font-weight: 500;
            color: #374151;
            margin-bottom: 6px;
        }}
        input {{
            width: 100%;
            padding: 12px 16px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.2s, box-shadow 0.2s;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        button {{
            width: 100%;
            padding: 14px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        button:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }}
        button:active {{
            transform: translateY(0);
        }}
        .error {{
            background: #fef2f2;
            border: 1px solid #fecaca;
            color: #dc2626;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .help {{
            margin-top: 24px;
            padding-top: 24px;
            border-top: 1px solid #e5e7eb;
            text-align: center;
        }}
        .help p {{
            color: #6b7280;
            font-size: 13px;
            line-height: 1.5;
        }}
        .help a {{
            color: #667eea;
            text-decoration: none;
        }}
        .help a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>Sokosumi MCP</h1>
            <p>Sign in to authorize access</p>
        </div>

        {error_html}

        <form method="POST" action="/oauth/login">
            <input type="hidden" name="session_id" value="{session_id}">

            <div class="form-group">
                <label for="api_key">Sokosumi API Key</label>
                <input
                    type="password"
                    id="api_key"
                    name="api_key"
                    placeholder="Enter your API key"
                    required
                    autocomplete="current-password"
                >
            </div>

            <button type="submit">Sign In & Authorize</button>
        </form>

        <div class="help">
            <p>
                Enter your Sokosumi API key to authorize this application.<br>
                <a href="https://app.sokosumi.com/settings/api-keys" target="_blank">Get your API key</a>
            </p>
        </div>
    </div>
</body>
</html>
"""
