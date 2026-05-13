#!/usr/bin/env python3
"""
Generate OpenAPI specs for all Python/FastAPI services.
Run from repository root: python scripts/generate-openapi.py
"""
import json
import sys
from pathlib import Path

# Add service source paths to sys.path
REPO_ROOT = Path(__file__).parent.parent
SERVICES = [
    "ai-service",
    "budget-service",
    "chatbot-service",
    "account-opening-service",
]


def generate_spec(service_name: str) -> dict:
    """Generate OpenAPI spec for a service by importing its FastAPI app."""
    service_path = REPO_ROOT / "src" / service_name
    sys.path.insert(0, str(service_path))
    
    try:
        from app.main import app
        spec = app.openapi()
        return spec
    finally:
        sys.path.pop(0)


def main():
    docs_api_dir = REPO_ROOT / "docs" / "api"
    docs_api_dir.mkdir(parents=True, exist_ok=True)
    
    for service in SERVICES:
        print(f"Generating OpenAPI spec for {service}...")
        spec = generate_spec(service)
        
        output_path = docs_api_dir / f"{service}-openapi.json"
        with open(output_path, "w") as f:
            json.dump(spec, f, indent=2)
        
        print(f"  → {output_path.relative_to(REPO_ROOT)}")
    
    print(f"\n✓ Generated {len(SERVICES)} OpenAPI specs")


if __name__ == "__main__":
    main()
