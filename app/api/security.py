import base64
import hmac
import json
import os
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="API access token")
USER_ACCESS_TOKEN_SECONDS = 12 * 60 * 60


def _signing_secret() -> bytes:
    secret = os.getenv("API_ACCESS_TOKEN", "").strip()
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )
    return secret.encode("utf-8")


def _encode_segment(value: dict) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def issue_user_access_token(username: str, role: str) -> tuple[str, int]:
    expires_at = int(time.time()) + USER_ACCESS_TOKEN_SECONDS
    header = _encode_segment({"alg": "HS256", "typ": "JWT"})
    payload = _encode_segment({
        "sub": username,
        "role": role,
        "iat": int(time.time()),
        "exp": expires_at,
    })
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(_signing_secret(), signing_input, "sha256").digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded_signature}", expires_at


def verify_user_access_token(token: str) -> dict:
    def reject() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if len(token) > 4096:
        reject()

    try:
        header_segment, payload_segment, signature_segment = token.split(".")
        header = json.loads(_decode_segment(header_segment))
        payload = json.loads(_decode_segment(payload_segment))
        signature = base64.urlsafe_b64decode(
            signature_segment + "=" * (-len(signature_segment) % 4),
        )
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        reject()

    expected_signature = hmac.new(_signing_secret(), signing_input, "sha256").digest()
    if not hmac.compare_digest(signature, expected_signature):
        reject()
    if header != {"alg": "HS256", "typ": "JWT"}:
        reject()
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("sub"), str)
        or not payload["sub"]
        or payload.get("role") not in {"authority", "inspector"}
        or not isinstance(payload.get("exp"), int)
        or not isinstance(payload.get("iat"), int)
        or payload["exp"] <= int(time.time())
        or payload["iat"] > int(time.time()) + 60
    ):
        reject()
    return payload


def require_authenticated_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A signed user session is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_user_access_token(credentials.credentials)


def require_authority_officer(
    claims: dict = Depends(require_authenticated_user),
) -> dict:
    if claims["role"] != "authority":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authority Officer access is required",
        )
    return claims


def _decode_segment(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def require_api_access(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> None:
    expected_token = os.getenv("API_ACCESS_TOKEN", "").strip()
    if len(expected_token) < 32:
        client_host = request.client.host if request.client else ""
        if os.getenv("APP_ENV", "development").strip().lower() == "development" and client_host in {
            "127.0.0.1",
            "::1",
            "::ffff:127.0.0.1",
        }:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if hmac.compare_digest(credentials.credentials, expected_token):
        return

    verify_user_access_token(credentials.credentials)