#!/usr/bin/env python3
"""Long-lived Transit client: cert auth (batch token) + encrypt/decrypt loop.

Batch tokens cannot be renewed. When TTL is close to expiry (or Vault rejects
the token), the app logs in again with the client certificate.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from datetime import datetime, timezone

import hvac
from hvac.exceptions import Forbidden, InvalidRequest, Unauthorized, VaultError

INTERVAL = int(os.getenv("LOOP_INTERVAL", "20"))
RELOGIN_SKEW = int(os.getenv("RELOGIN_SKEW", "10"))
CERT_NAME = os.getenv("VAULT_CERT_NAME", "transit")
KEY_NAME = os.getenv("TRANSIT_KEY", "kms")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")


def token_fp(token: str | None) -> str:
    if not token:
        return "<none>"
    return token[:28] + "..."


def make_client() -> hvac.Client:
    return hvac.Client(
        url=os.environ["VAULT_ADDR"],
        cert=(os.environ["VAULT_CLIENT_CERT"], os.environ["VAULT_CLIENT_KEY"]),
        verify=os.environ.get("VAULT_CACERT") or True,
    )


def login(client: hvac.Client) -> tuple[str, float]:
    response = client.auth.cert.login(name=CERT_NAME)
    auth = response["auth"] if isinstance(response, dict) and "auth" in response else response
    token = auth.get("client_token") or client.token
    ttl = int(auth.get("lease_duration") or 0)
    expires_at = time.time() + ttl
    print(
        f"[{now()}] LOGIN type={auth.get('token_type')} "
        f"renewable={auth.get('renewable')} ttl={ttl}s "
        f"token={token_fp(token)}",
        flush=True,
    )
    return token, expires_at


def roundtrip(client: hvac.Client, seq: int) -> None:
    plaintext = f"python-{seq}-{uuid.uuid4().hex[:8]}"
    encrypted = client.secrets.transit.encrypt_data(
        name=KEY_NAME,
        plaintext=base64.b64encode(plaintext.encode()).decode(),
    )
    ciphertext = encrypted["data"]["ciphertext"]
    decrypted = client.secrets.transit.decrypt_data(name=KEY_NAME, ciphertext=ciphertext)
    out = base64.b64decode(decrypted["data"]["plaintext"]).decode()
    if out != plaintext:
        raise RuntimeError(f"decrypt mismatch: {out!r} != {plaintext!r}")
    print(
        f"[{now()}] OK seq={seq} token={token_fp(client.token)} "
        f"plain={plaintext} cipher={ciphertext[:36]}...",
        flush=True,
    )


def main() -> None:
    client = make_client()
    _, expires_at = login(client)
    seq = 0
    print(
        f"[{now()}] looping every {INTERVAL}s; re-login when TTL < {RELOGIN_SKEW}s",
        flush=True,
    )
    while True:
        seq += 1
        try:
            if expires_at - time.time() < RELOGIN_SKEW:
                print(f"[{now()}] token near expiry; obtaining a new one", flush=True)
                _, expires_at = login(client)
            roundtrip(client, seq)
        except (Forbidden, Unauthorized, InvalidRequest, VaultError) as exc:
            print(f"[{now()}] Vault rejected the token ({exc}); re-login", flush=True)
            _, expires_at = login(client)
            roundtrip(client, seq)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
