"""
OAuth 2.1 Implementation for Sokosumi MCP Server.

This module implements:
1. OAuth CLIENT - redirects users to Sokosumi's OAuth provider for authentication
2. OAuth SERVER - issues JWTs to MCP clients (mcp-remote) after Sokosumi auth

Flow:
1. mcp-remote → MCP /oauth/authorize
2. MCP → Sokosumi /auth/oauth2/authorize (user logs in)
3. Sokosumi → MCP /oauth/callback (with auth code)
4. MCP exchanges code with Sokosumi for access token
5. MCP → mcp-remote callback (with MCP's auth code)
6. mcp-remote → MCP /oauth/token (exchange for MCP JWT)
"""

import os
import time
import secrets
import hashlib
import base64
import logging
import httpx
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

# Server URLs
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "https://mcp.sokosumi.com")

# Sokosumi OAuth configuration
SOKOSUMI_OAUTH_BASE_URL = os.environ.get("SOKOSUMI_OAUTH_BASE_URL", "https://app.sokosumi.com")
SOKOSUMI_AUTH_ENDPOINT = f"{SOKOSUMI_OAUTH_BASE_URL}/auth/oauth2/authorize"
SOKOSUMI_TOKEN_ENDPOINT = f"{SOKOSUMI_OAUTH_BASE_URL}/auth/oauth2/token"

# OAuth client credentials (set via environment)
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = f"{MCP_SERVER_URL}/oauth/callback"

# RSA Key Management for JWT signing
_private_key = None
_public_key = None
_key_id = None

# Session storage
_mcp_sessions: Dict[str, Dict[str, Any]] = {}  # MCP client sessions (from mcp-remote)
_sokosumi_sessions: Dict[str, Dict[str, Any]] = {}  # Sokosumi OAuth state tracking
_auth_codes: Dict[str, Dict[str, Any]] = {}  # MCP auth codes (issued to mcp-remote)
_refresh_tokens: Dict[str, Dict[str, Any]] = {}

# Token settings
ACCESS_TOKEN_EXPIRY = 3600  # 1 hour
REFRESH_TOKEN_EXPIRY = 86400 * 30  # 30 days
AUTH_CODE_EXPIRY = 600  # 10 minutes
SESSION_EXPIRY = 600  # 10 minutes


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

    _private_key, _public_key, _key_id = _generate_rsa_keys()


def get_keys():
    """Get the current RSA key pair, initializing if needed."""
    global _private_key, _public_key, _key_id
    if _private_key is None:
        _load_or_generate_keys()
    return _private_key, _public_key, _key_id


def get_jwks() -> Dict[str, Any]:
    """Get the JWKS containing our public key for JWT verification."""
    _, public_key, key_id = get_keys()
    public_numbers = public_key.public_numbers()

    def int_to_base64url(n: int, length: int) -> str:
        data = n.to_bytes(length, byteorder='big')
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

    n = int_to_base64url(public_numbers.n, 256)
    e = int_to_base64url(public_numbers.e, 3)

    return {
        "keys": [{
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": key_id,
            "n": n,
            "e": e,
        }]
    }


def get_protected_resource_metadata() -> Dict[str, Any]:
    """OAuth 2.0 Protected Resource Metadata (RFC 9728)."""
    return {
        "resource": MCP_SERVER_URL,
        "authorization_servers": [MCP_SERVER_URL],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp:read", "mcp:write"],
    }


def get_authorization_server_metadata() -> Dict[str, Any]:
    """OAuth 2.0 Authorization Server Metadata (RFC 8414)."""
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
    """Get WWW-Authenticate header for 401 responses."""
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


# ============================================================================
# MCP Session Management (sessions from mcp-remote clients)
# ============================================================================

def create_mcp_session(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    scope: str,
    state: str,
    resource: Optional[str] = None,
) -> str:
    """Create a new MCP client session (from mcp-remote)."""
    session_id = secrets.token_urlsafe(32)

    _mcp_sessions[session_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
        "state": state,
        "resource": resource,
        "created_at": time.time(),
    }

    _cleanup_expired_sessions()
    logger.info(f"Created MCP session: {session_id[:8]}...")
    return session_id


def get_mcp_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get an MCP session by ID."""
    session = _mcp_sessions.get(session_id)
    if not session:
        return None
    if time.time() - session["created_at"] > SESSION_EXPIRY:
        del _mcp_sessions[session_id]
        return None
    return session


# ============================================================================
# Sokosumi OAuth Client Functions
# ============================================================================

def build_sokosumi_auth_url(mcp_session_id: str) -> str:
    """
    Build the Sokosumi OAuth authorization URL.

    Creates a PKCE code verifier/challenge for the Sokosumi OAuth flow
    and stores it for later token exchange.
    """
    # Generate PKCE for Sokosumi
    sokosumi_code_verifier = generate_code_verifier()
    sokosumi_code_challenge = generate_code_challenge(sokosumi_code_verifier)

    # Use MCP session ID as state to link back
    sokosumi_state = secrets.token_urlsafe(32)

    # Store Sokosumi session for callback
    _sokosumi_sessions[sokosumi_state] = {
        "mcp_session_id": mcp_session_id,
        "code_verifier": sokosumi_code_verifier,
        "created_at": time.time(),
    }

    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": "openid profile email",  # Sokosumi scopes
        "state": sokosumi_state,
        "code_challenge": sokosumi_code_challenge,
        "code_challenge_method": "S256",
    }

    url = f"{SOKOSUMI_AUTH_ENDPOINT}?{urlencode(params)}"
    logger.info(f"Built Sokosumi auth URL for MCP session {mcp_session_id[:8]}...")
    return url


async def exchange_sokosumi_code(code: str, state: str) -> Dict[str, Any]:
    """
    Exchange Sokosumi authorization code for tokens.

    Returns:
        Dict with access_token, user info, and mcp_session_id
    """
    sokosumi_session = _sokosumi_sessions.pop(state, None)
    if not sokosumi_session:
        raise ValueError("Invalid or expired state")

    if time.time() - sokosumi_session["created_at"] > SESSION_EXPIRY:
        raise ValueError("Session expired")

    # Exchange code for tokens with Sokosumi
    async with httpx.AsyncClient() as client:
        response = await client.post(
            SOKOSUMI_TOKEN_ENDPOINT,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "client_id": OAUTH_CLIENT_ID,
                "client_secret": OAUTH_CLIENT_SECRET,
                "code_verifier": sokosumi_session["code_verifier"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )

        if response.status_code != 200:
            logger.error(f"Sokosumi token exchange failed: {response.status_code} - {response.text}")
            raise ValueError(f"Token exchange failed: {response.text}")

        token_data = response.json()
        logger.info("Successfully exchanged Sokosumi auth code for tokens")

        return {
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "id_token": token_data.get("id_token"),
            "mcp_session_id": sokosumi_session["mcp_session_id"],
        }


# ============================================================================
# MCP Auth Code Generation (for mcp-remote)
# ============================================================================

def create_mcp_auth_code(mcp_session_id: str, sokosumi_access_token: str, user_id: str) -> str:
    """
    Create an MCP authorization code after successful Sokosumi authentication.

    This code will be sent back to mcp-remote for exchange.
    """
    session = _mcp_sessions.pop(mcp_session_id, None)
    if not session:
        raise ValueError("Invalid MCP session")

    code = secrets.token_urlsafe(32)

    _auth_codes[code] = {
        **session,
        "user_id": user_id,
        "sokosumi_access_token": sokosumi_access_token,
        "code_created_at": time.time(),
    }

    logger.info(f"Created MCP auth code for user: {user_id}")
    return code


def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    client_id: str,
    redirect_uri: str,
) -> Dict[str, Any]:
    """
    Exchange MCP authorization code for MCP tokens.

    Called by mcp-remote to get JWT access token.
    """
    auth_data = _auth_codes.pop(code, None)
    if not auth_data:
        raise ValueError("Invalid authorization code")

    if time.time() - auth_data["code_created_at"] > AUTH_CODE_EXPIRY:
        raise ValueError("Authorization code expired")

    if auth_data["client_id"] != client_id:
        raise ValueError("Client ID mismatch")

    if auth_data["redirect_uri"] != redirect_uri:
        raise ValueError("Redirect URI mismatch")

    if auth_data["code_challenge_method"] != "S256":
        raise ValueError("Unsupported code challenge method")

    if not verify_code_challenge(code_verifier, auth_data["code_challenge"]):
        raise ValueError("Invalid code verifier")

    # Generate MCP tokens
    access_token = _create_access_token(
        user_id=auth_data["user_id"],
        sokosumi_token=auth_data["sokosumi_access_token"],
        scope=auth_data["scope"],
        client_id=client_id,
    )

    refresh_token = _create_refresh_token(
        user_id=auth_data["user_id"],
        sokosumi_token=auth_data["sokosumi_access_token"],
        scope=auth_data["scope"],
        client_id=client_id,
    )

    logger.info(f"Exchanged MCP code for tokens for user: {auth_data['user_id']}")

    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRY,
        "refresh_token": refresh_token,
        "scope": auth_data["scope"],
    }


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """Refresh an MCP access token."""
    token_data = _refresh_tokens.get(refresh_token)
    if not token_data:
        raise ValueError("Invalid refresh token")

    if time.time() - token_data["created_at"] > REFRESH_TOKEN_EXPIRY:
        del _refresh_tokens[refresh_token]
        raise ValueError("Refresh token expired")

    access_token = _create_access_token(
        user_id=token_data["user_id"],
        sokosumi_token=token_data["sokosumi_token"],
        scope=token_data["scope"],
        client_id=token_data["client_id"],
    )

    # Rotate refresh token
    del _refresh_tokens[refresh_token]
    new_refresh_token = _create_refresh_token(
        user_id=token_data["user_id"],
        sokosumi_token=token_data["sokosumi_token"],
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
    sokosumi_token: str,
    scope: str,
    client_id: str,
) -> str:
    """Create a signed JWT access token for MCP clients."""
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
        "sokosumi_token": sokosumi_token,  # Include for downstream API calls
    }

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _create_refresh_token(
    user_id: str,
    sokosumi_token: str,
    scope: str,
    client_id: str,
) -> str:
    """Create a refresh token and store it."""
    token = secrets.token_urlsafe(64)

    _refresh_tokens[token] = {
        "user_id": user_id,
        "sokosumi_token": sokosumi_token,
        "scope": scope,
        "client_id": client_id,
        "created_at": time.time(),
    }

    return token


async def validate_access_token(token: str) -> Dict[str, Any]:
    """Validate an MCP access token and return the payload."""
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
    """Clean up expired sessions and tokens."""
    current_time = time.time()

    # Clean MCP sessions
    expired = [sid for sid, s in _mcp_sessions.items() if current_time - s["created_at"] > SESSION_EXPIRY]
    for sid in expired:
        del _mcp_sessions[sid]

    # Clean Sokosumi sessions
    expired = [sid for sid, s in _sokosumi_sessions.items() if current_time - s["created_at"] > SESSION_EXPIRY]
    for sid in expired:
        del _sokosumi_sessions[sid]

    # Clean auth codes
    expired = [code for code, data in _auth_codes.items() if current_time - data["code_created_at"] > AUTH_CODE_EXPIRY]
    for code in expired:
        del _auth_codes[code]

    # Clean refresh tokens
    expired = [token for token, data in _refresh_tokens.items() if current_time - data["created_at"] > REFRESH_TOKEN_EXPIRY]
    for token in expired:
        del _refresh_tokens[token]

    if expired:
        logger.info(f"Cleaned up expired sessions/tokens")
