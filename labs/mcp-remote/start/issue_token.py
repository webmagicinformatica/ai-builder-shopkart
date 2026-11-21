"""A stand-in for the AUTHORIZATION SERVER: it signs short-lived tokens for the ticket MCP server.

In production this is your company's identity provider (Cognito, Entra ID, Okta, Keycloak...).
It runs the login page and PKCE, and issues tokens. Here a script plays that role, so the lab
can focus on the resource server: what the MCP server must check on every request.

    uv run python labs/mcp-remote/done/issue_token.py keygen
    uv run python labs/mcp-remote/done/issue_token.py token --sub asha@shopkart.in --scope tickets:read --aud $MCP_URL

keygen writes the PRIVATE key to .shopkart/mcp-issuer.pem (gitignored; it never leaves your
Codespace) and the PUBLIC key to .shopkart/mcp-issuer.pub. Only the public key goes to the server.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[3]
KEYS = ROOT / ".shopkart"
ISSUER = "https://auth.shopkart.example"  # our pretend authorization server
SCOPES = ("tickets:read", "tickets:write")


def keygen(folder: Path = KEYS) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = folder / "mcp-issuer.pem"
    public = folder / "mcp-issuer.pub"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    private.chmod(0o600)
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo))
    return private, public


def issue(private_pem: bytes, *, sub: str, scope: str, aud: str, ttl_s: int = 3600,
          client_id: str = "shopkart-copilot", now: float | None = None) -> str:
    """A signed token: who (sub), for which server (aud), allowed to do what (scope), until when (exp)."""
    unknown = set(scope.split()) - set(SCOPES)
    if unknown:
        raise ValueError(f"unknown scope {sorted(unknown)}; use {' or '.join(SCOPES)}")
    now = int(now or time.time())
    claims = {"iss": ISSUER, "sub": sub, "aud": aud, "scope": scope, "client_id": client_id,
              "iat": now, "exp": now + ttl_s, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, private_pem, algorithm="RS256")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Issue tokens for the ShopKart ticket MCP server")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="make the signing key pair")
    t = sub.add_parser("token", help="issue a token")
    t.add_argument("--sub", required=True, help="who: the staff member's login")
    t.add_argument("--scope", default="tickets:read", help='"tickets:read" or "tickets:read tickets:write"')
    t.add_argument("--aud", required=True, help="the MCP server's URL, ending in /mcp")
    t.add_argument("--ttl", type=int, default=3600, help="seconds until it expires (default 1 hour)")
    args = p.parse_args(argv)
    if args.cmd == "keygen":
        private, public = keygen()
        print(f"private key: {private} (stays here)\npublic key:  {public} (goes to the server)", file=sys.stderr)
        return 0
    print(issue((KEYS / "mcp-issuer.pem").read_bytes(), sub=args.sub, scope=args.scope, aud=args.aud, ttl_s=args.ttl))
    return 0


if __name__ == "__main__":
    sys.exit(main())
