#!/usr/bin/env python3
"""
generate_secrets.py — Generate cryptographically secure secrets for KisanQueue.

Outputs random 32-byte hex keys suitable for:
  - JWT_SECRET_KEY
  - QR_HMAC_SECRET

Usage:
  python generate_secrets.py
"""
from __future__ import annotations

import secrets
import sys


def generate_secrets() -> tuple[str, str]:
    jwt_secret = secrets.token_hex(32)
    qr_secret = secrets.token_hex(32)
    while qr_secret == jwt_secret:
        qr_secret = secrets.token_hex(32)
    return jwt_secret, qr_secret


def main() -> None:
    jwt_secret, qr_secret = generate_secrets()

    print("=" * 60)
    print("  KisanQueue Cryptographic Secret Generator")
    print("=" * 60)
    print("\nPaste the following into your backend/.env file:\n")
    print(f"JWT_SECRET_KEY={jwt_secret}")
    print(f"QR_HMAC_SECRET={qr_secret}")
    print("\nNote: Both secrets are generated using Python's cryptographically")
    print("secure secrets.token_hex(32) and are guaranteed to be distinct.")
    print("=" * 60)


if __name__ == "__main__":
    main()
