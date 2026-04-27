"""
OAuth metadata and proxy helpers for the Sokosumi MCP server.

This MCP server acts as a protected resource. It does not mint its own access
tokens. Instead, it advertises Sokosumi Better Auth as the authorization
server and keeps local /oauth/* routes as thin compatibility proxies.
"""

import os
from typing import Any, Dict, Optional
from urllib.parse import urlencode

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "https://mcp.sokosumi.com").rstrip("/")
MAINNET_AUTH_BASE_URL = os.environ.get("MAINNET_AUTH_BASE_URL", "https://app.sokosumi.com").rstrip("/")
PREPROD_AUTH_BASE_URL = os.environ.get("PREPROD_AUTH_BASE_URL", "https://preprod.sokosumi.com").rstrip("/")


def normalize_network(network: Optional[str]) -> str:
    """Normalize any unknown network to mainnet."""
    return "preprod" if network == "preprod" else "mainnet"


def get_auth_base_url(network: Optional[str] = None) -> str:
    """Get the Sokosumi app base URL for the selected network."""
    if normalize_network(network) == "preprod":
        return PREPROD_AUTH_BASE_URL
    return MAINNET_AUTH_BASE_URL


def get_auth_issuer(network: Optional[str] = None) -> str:
    """Get the canonical Better Auth issuer URL."""
    return f"{get_auth_base_url(network)}/api/auth"


def get_oauth_base_url(network: Optional[str] = None) -> str:
    """Get the Better Auth OAuth 2.1 endpoint base URL."""
    return f"{get_auth_issuer(network)}/oauth2"


def get_jwks_url(network: Optional[str] = None) -> str:
    """Get the Better Auth JWKS URL."""
    return f"{get_auth_issuer(network)}/jwks"


def build_proxy_url(
    path: str,
    network: Optional[str] = None,
    query_params: Optional[Dict[str, Any]] = None,
) -> str:
    """Build an upstream OAuth URL for a compatibility proxy route."""
    base_url = get_jwks_url(network) if path == "/jwks" else f"{get_oauth_base_url(network)}{path}"
    if not query_params:
        return base_url

    encoded = urlencode(query_params, doseq=True)
    return f"{base_url}?{encoded}" if encoded else base_url


def get_protected_resource_metadata(network: Optional[str] = None) -> Dict[str, Any]:
    """OAuth 2.0 Protected Resource Metadata (RFC 9728)."""
    return {
        "resource": MCP_SERVER_URL,
        "authorization_servers": [MCP_SERVER_URL],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["openid", "offline_access"],
    }


def get_authorization_server_metadata(network: Optional[str] = None) -> Dict[str, Any]:
    """Return the Sokosumi Better Auth authorization server metadata."""
    issuer = get_auth_issuer(network)
    oauth_base_path = f"{issuer}/oauth2"

    return {
        "issuer": issuer,
        "authorization_endpoint": f"{oauth_base_path}/authorize",
        "token_endpoint": f"{oauth_base_path}/token",
        "registration_endpoint": f"{oauth_base_path}/register",
        "revocation_endpoint": f"{oauth_base_path}/revoke",
        "introspection_endpoint": f"{oauth_base_path}/introspect",
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "authorization_code",
            "refresh_token",
            "client_credentials",
        ],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256", "plain"],
        "scopes_supported": ["openid", "offline_access"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
    }


def get_www_authenticate_header(
    network: Optional[str] = None,
    scope: Optional[str] = None,
) -> str:
    """Get the WWW-Authenticate header for 401 responses."""
    resource_metadata_url = f"{MCP_SERVER_URL}/.well-known/oauth-protected-resource"
    if normalize_network(network) == "preprod":
        resource_metadata_url = f"{resource_metadata_url}?network=preprod"

    header = f'Bearer resource_metadata="{resource_metadata_url}"'
    if scope:
        header += f', scope="{scope}"'
    return header
