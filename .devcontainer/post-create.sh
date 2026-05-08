#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Installing go-task..."
sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin

echo "📦 Installing UI dependencies..."
if [ -d "src/ui-app" ]; then
  cd src/ui-app && npm install && cd ../..
fi

echo "📦 Installing E2E test dependencies..."
if [ -d "tests/e2e" ]; then
  cd tests/e2e && npm install && cd ../..
fi

echo "📦 Installing Python dependencies..."
for svc in src/ai-service src/chatbot-service src/budget-service src/prompt-eval-service; do
  if [ -f "$svc/requirements.txt" ]; then
    echo "  → $svc"
    pip install -q -r "$svc/requirements.txt" 2>/dev/null || true
  fi
done

echo "✅ DevContainer setup complete!"
echo ""
echo "Quick start:"
echo "  Local:  docker-compose up -d"
echo "  Cloud:  task -t Taskfile.cloud.yml up"
echo "  Tests:  task e2e:run"
