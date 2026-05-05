#!/bin/bash
# Deploy AI components to Azure AI Foundry

set -e

echo "Deploying AI components to Azure AI Foundry..."

# Deploy infrastructure with Terraform
echo "Step 1: Deploying Azure infrastructure..."
cd infra/terraform
terraform init -backend-config="key=ai-foundry.tfstate" -backend-config="resource_group_name=${RESOURCE_GROUP:-banking-demo-rg}" -backend-config="storage_account_name=${STORAGE_ACCOUNT:-bankingdemostorage}" ${BACKEND_CONFIG:-}
terraform apply -var="prefix=bankingdemo" -auto-approve

# Get outputs
OPENAI_ENDPOINT=$(terraform output -raw openai_endpoint)
OPENAI_KEY=$(terraform output -raw openai_key)
HUB_NAME=$(terraform output -raw ai_hub_name)
PROJECT_NAME=$(terraform output -raw ai_project_name)

cd ../..

# Install Azure CLI AI extension
echo "Step 2: Installing Azure AI extension..."
az extension add --name ml -y --yes

# Create AI agents
echo "Step 3: Creating AI agents..."
az ai project create \
  --resource-group bankingdemo-ai-rg \
  --name $PROJECT_NAME \
  --hub-name $HUB_NAME \
  --location eastus

# Deploy model endpoints
echo "Step 4: Deploying model endpoints..."
az cognitiveservices account deployment create \
  --resource-group bankingdemo-ai-rg \
  --name bankingdemo-openai \
  --deployment-name gpt-4o-mini \
  --model-name gpt-4o-mini \
  --model-version "2024-07-18" \
  --model-format OpenAI \
  --sku-name GlobalStandard \
  --sku-tier Global

# Create environment variables for local development
echo "Step 5: Creating environment configuration..."
cat > .env.ai << EOF
# Azure AI Foundry Configuration
AZURE_OPENAI_ENDPOINT=$OPENAI_ENDPOINT
AZURE_OPENAI_KEY=$OPENAI_KEY
AZURE_OPENAI_MODEL=gpt-4o-mini
APPLICATIONINSIGHTS_CONNECTION_STRING=$(terraform -chdir=infra/terraform output -raw app_insights_connection_string)
EOF

echo "Deployment complete!"
echo "AI components deployed:"
echo "  - Chatbot Agent (financial-advisor-agent)"
echo "  - Anomaly Detection Agent (fraud-detection-agent)"  
echo "  - Budget Analysis Agent (budget-analysis-agent)"
echo "  - Model: gpt-4o-mini"
echo ""
echo "Run 'source .env.ai' to configure your environment"