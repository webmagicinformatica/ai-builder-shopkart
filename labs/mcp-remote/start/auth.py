"""The MCP server as an OAuth RESOURCE SERVER: it never shows a login page, it only checks tokens.

Every request carries `Authorization: Bearer <token>`. The token is a signed JWT, and we check:
  - signed by OUR authorization server (its public key)   -> not forged
  - not expired                                            -> exp
  - made for THIS server (audience = our URL)              -> aud. No token passthrough.
  - which scopes it carries                                -> tickets:read, tickets:write

Scopes (least privilege: two small ones, not one "admin"):
  tickets:read    search_tickets, get_ticket, the ticket resource, the summarise prompt
  tickets:write   add_note, set_status (they change things)

A token with only tickets:read that calls a write tool gets 403 insufficient_scope, naming the
scope it needs. The client then asks the user to approve it: step-up authorization.
"""

from __future__ import annotations

import json
import os

import jwt
from mcp.server.auth.provider import AccessToken

READ, WRITE = "tickets:read", "tickets:write"
WRITE_TOOLS = {"add_note", "set_status"}


class JWTVerifier:
    """The MCP SDK calls verify_token() on every request. None means: 401, log in again."""

    def __init__(self, public_key_pem: str, issuer: str, audience: str):
        self.public_key = public_key_pem
        self.issuer = issuer
        self.audience = audience

    @classmethod
    def from_env(cls) -> JWTVerifier:
        return cls(os.environ["MCP_JWT_PUBLIC_KEY"], os.environ["MCP_ISSUER"], os.environ["MCP_RESOURCE_URL"])

    def claims(self, token: str) -> dict | None:
        # TODO 1: check the token with jwt.decode(): our public key, algorithms=["RS256"] ONLY,
        #   issuer=self.issuer, audience=self.audience, and require exp, sub, aud and iss.
        #   Return the claims, or None when jwt raises any jwt.PyJWTError (bad signature, expired,
        #   made for another server...). None means 401.
        return None

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = self.claims(token)
        if claims is None:
            return None
        return AccessToken(token=token, client_id=claims.get("client_id", "unknown"),
                           scopes=claims.get("scope", "").split(), expires_at=claims["exp"],
                           resource=self.audience, subject=claims["sub"], claims=claims)


class StepUpScopes:
    """ASGI middleware: a write tool needs tickets:write. Without it: 403 insufficient_scope.

    The SDK already refuses requests without a valid token (401) and checks the basic scope.
    This adds the per-tool check, at the HTTP level, so the client knows WHICH scope to ask for."""

    def __init__(self, app, verifier: JWTVerifier, resource_metadata_url: str, path: str = "/mcp"):
        self.app = app
        self.verifier = verifier
        self.metadata_url = resource_metadata_url
        self.path = path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"].rstrip("/") != self.path:
            return await self.app(scope, receive, send)
        body = b""
        while True:  # read the whole body, then hand it on unchanged
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        if self._needs_write(body) and not self._has_write(scope):
            return await self._forbidden(send)

        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    def _needs_write(body: bytes) -> bool:
        try:
            msg = json.loads(body)
        except ValueError:
            return False
        msgs = msg if isinstance(msg, list) else [msg]
        return any(isinstance(m, dict) and m.get("method") == "tools/call"
                   and (m.get("params") or {}).get("name") in WRITE_TOOLS for m in msgs)

    def _has_write(self, scope) -> bool:
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode()
        if not auth.lower().startswith("bearer "):
            return True  # no token at all: let the SDK answer 401
        claims = self.verifier.claims(auth[7:])
        if claims is None:
            return True  # bad token: the SDK answers 401
        # TODO 2: least privilege. Return True only if the token's "scope" claim (space-separated)
        #   contains WRITE. Then a read-only token calling add_note gets 403 insufficient_scope.
        return True

    async def _forbidden(self, send):
        body = json.dumps({"error": "insufficient_scope", "error_description": f"Required scope: {WRITE}"}).encode()
        www = (f'Bearer error="insufficient_scope", scope="{READ} {WRITE}", '
               f'resource_metadata="{self.metadata_url}", error_description="Required scope: {WRITE}"')
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", www.encode())]})
        await send({"type": "http.response.body", "body": body})
