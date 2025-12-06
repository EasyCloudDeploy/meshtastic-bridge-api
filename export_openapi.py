#!/usr/bin/env python3
"""Export OpenAPI specification to YAML and JSON files."""

import json
import sys
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from meshtastic_relay_api.main import app


def export_openapi():
    """Export OpenAPI spec to YAML and JSON files."""
    # Get OpenAPI schema
    openapi_schema = app.openapi()

    # Export to JSON
    json_path = Path(__file__).parent / "openapi.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
    print(f"✓ Exported OpenAPI spec to {json_path}")

    # Export to YAML
    yaml_path = Path(__file__).parent / "openapi.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(openapi_schema, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"✓ Exported OpenAPI spec to {yaml_path}")

    print(f"\nOpenAPI spec version: {openapi_schema.get('info', {}).get('version', 'unknown')}")
    print(f"Total endpoints: {len(openapi_schema.get('paths', {}))}")


if __name__ == "__main__":
    try:
        export_openapi()
    except ImportError as e:
        print(f"Error: {e}")
        print("\nPlease install required dependencies:")
        print("  pip install pyyaml")
        sys.exit(1)
    except Exception as e:
        print(f"Error exporting OpenAPI spec: {e}", file=sys.stderr)
        sys.exit(1)

