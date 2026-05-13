#!/bin/bash
# Generate OpenAPI specs for all .NET services
# Run this from the repository root: ./scripts/generate-openapi-specs.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "Installing Swashbuckle CLI tool (if not already installed)..."
dotnet tool install --global Swashbuckle.AspNetCore.Cli --version 6.9.0 2>/dev/null || true

echo ""
echo "Building and generating OpenAPI specs for .NET services..."
echo ""

# Common environment variables for OpenAPI generation
export UseInMemoryDatabase=true
export Jwt__Key="test-key-for-openapi-generation-only-32chars-minimum"
export Jwt__Issuer="test-issuer"
export Jwt__Audience="test-audience"
export CosmosDb__ConnectionString="AccountEndpoint=https://localhost:8081/;AccountKey=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="

# Services that can be built and processed directly
SIMPLE_SERVICES=("user-service" "account-service" "transaction-service" "transfer-service")

for service in "${SIMPLE_SERVICES[@]}"; do
  echo "Processing $service..."
  cd "$REPO_ROOT/src/$service"
  
  # Build the service
  dotnet build -o "$REPO_ROOT/.build/openapi-gen/$service/bin/Debug/net9.0" > /dev/null 2>&1
  
  # Generate OpenAPI spec
  swagger tofile \
    --output "$REPO_ROOT/docs/api/${service}-openapi.json" \
    "$REPO_ROOT/.build/openapi-gen/$service/bin/Debug/net9.0/${service}.dll" \
    v1 > /dev/null 2>&1
  
  echo "✓ Generated docs/api/${service}-openapi.json"
done

# prompt-eval-service requires special handling due to startup initialization
echo "Processing prompt-eval-service (requires temporary code modification)..."
cd "$REPO_ROOT/src/prompt-eval-service"

# Backup Program.cs
cp Program.cs Program.cs.bak

# Temporarily comment out Cosmos initialization that runs on startup
sed -i '108,113s/^/\/\/ /' Program.cs

# Build
dotnet build -o "$REPO_ROOT/.build/openapi-gen/prompt-eval-service/bin/Debug/net9.0" > /dev/null 2>&1

# Generate spec
cd "$REPO_ROOT"
swagger tofile \
  --output "$REPO_ROOT/docs/api/prompt-eval-service-openapi.json" \
  "$REPO_ROOT/.build/openapi-gen/prompt-eval-service/bin/Debug/net9.0/prompt-eval-service.dll" \
  v1 > /dev/null 2>&1

# Restore Program.cs
cd "$REPO_ROOT/src/prompt-eval-service"
mv Program.cs.bak Program.cs

echo "✓ Generated docs/api/prompt-eval-service-openapi.json"

echo ""
echo "All OpenAPI specs generated successfully!"
echo ""
echo "Generated specs:"
ls -1 "$REPO_ROOT/docs/api/"*-service-openapi.json | grep -E "(user|account|transaction|transfer|prompt-eval)" | sed 's|.*/|  - |'
