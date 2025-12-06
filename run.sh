#!/bin/bash
# Quick start script for Meshtastic Relay API

set -e

# Check if UV is installed
if ! command -v uv &> /dev/null; then
    echo "Error: UV is not installed. Install it with:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Install dependencies
echo "Installing/updating dependencies..."
uv pip install -e .

# Run the API using UV's environment
echo "Starting Meshtastic Relay API..."
uv run uvicorn meshtastic_relay_api.main:app --host 0.0.0.0 --port 8000

