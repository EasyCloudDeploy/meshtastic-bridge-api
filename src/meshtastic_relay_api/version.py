"""Version management for Meshtastic Relay API."""

import os
from pathlib import Path


def get_version() -> str:
    """
    Get the application version.
    
    Checks in order:
    1. APP_VERSION environment variable (set during Docker build)
    2. VERSION file in project root
    3. Fallback to "unknown"
    
    Returns:
        Version string
    """
    # First, check environment variable (set during Docker build)
    env_version = os.getenv("APP_VERSION")
    if env_version:
        return env_version.strip()
    
    # Try to read from VERSION file
    # Look for VERSION file relative to this file's location
    # Go up from src/meshtastic_relay_api/version.py to project root
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    version_file = project_root / "VERSION"
    
    # Also check /app/VERSION (Docker container path)
    docker_version_file = Path("/app/VERSION")
    
    for vfile in [version_file, docker_version_file]:
        if vfile.exists():
            try:
                with open(vfile, "r", encoding="utf-8") as f:
                    version = f.read().strip()
                    if version:
                        return version
            except Exception:
                continue
    
    # Fallback
    return "unknown"

