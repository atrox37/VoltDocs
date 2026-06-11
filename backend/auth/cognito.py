from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from urllib.parse import quote

import httpx


@dataclass
class TokenSet:
    access_token: str
    id_token: str
    refresh_token: str | None


@dataclass
class Claims:
    email: str
    name: str


class CognitoClient:
    def __init__(self, domain: str, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.domain = domain.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorization_url(self, state: str) -> str:
        return (
            f"{self.domain}/oauth2/authorize"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={quote(self.redirect_uri)}"
            f"&scope=openid%20email%20profile"
            f"&identity_provider=MicrosoftTeamsOIDC"
            f"&state={state}"
        )

    async def exchange_code(self, code: str) -> TokenSet:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        return await self._token_request(payload)

    async def refresh_tokens(self, refresh_token: str) -> TokenSet:
        """Use a Cognito refresh token to obtain a new access + id token pair."""
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": refresh_token,
        }
        return await self._token_request(payload)

    async def _token_request(self, payload: dict) -> TokenSet:
        headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded"}
        if self.client_secret:
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {basic}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.domain}/oauth2/token", data=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return TokenSet(
            access_token=data["access_token"],
            id_token=data.get("id_token", ""),
            # Cognito does NOT return a new refresh_token on refresh — reuse the old one
            refresh_token=data.get("refresh_token"),
        )


def _derive_name_from_email(email: str) -> str:
    """从 email 前缀推导显示名，如 zhiyuan.wang@... → Zhiyuan Wang"""
    prefix = email.split("@")[0]
    parts = prefix.split(".")
    return " ".join(p.capitalize() for p in parts if p)


def extract_claims(id_token: str) -> Claims:
    parts = id_token.split(".")
    if len(parts) < 2:
        raise ValueError("invalid JWT")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))

    email = payload.get("email", "")

    # 优先使用 name 字段（Microsoft 通常会填）
    raw_name: str = payload.get("name", "")

    # 如果 name 看起来是 Cognito 内部 username（含下划线或超长），丢弃它
    if raw_name and ("_" in raw_name or len(raw_name) > 50):
        raw_name = ""

    if not raw_name:
        # 尝试 given_name + family_name
        given = payload.get("given_name", "")
        family = payload.get("family_name", "")
        raw_name = f"{given} {family}".strip()

    if not raw_name and email:
        # 最后回退：从 email 前缀推导
        raw_name = _derive_name_from_email(email)

    return Claims(email=email, name=raw_name or email)


def generate_state() -> str:
    return secrets.token_hex(16)
