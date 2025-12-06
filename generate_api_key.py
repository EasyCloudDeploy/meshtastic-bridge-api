#!/usr/bin/env python3
"""Generate a secure API key for Meshtastic Relay API."""

import secrets
import sys


def generate_api_key() -> str:
    """
    Generate a secure random API key.

    Returns:
        A secure random API key (32 bytes, URL-safe base64 encoded)
    """
    return secrets.token_urlsafe(32)


def main() -> None:
    """Generate and print API key."""
    api_key = generate_api_key()
    print("Generated API Key:")
    print(api_key)
    print("\nAdd this to your .env file:")
    print(f"API_KEYS={api_key}")
    print("\nOr add to existing API_KEYS (comma-separated):")
    print(f"API_KEYS=existing-key,{api_key}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

