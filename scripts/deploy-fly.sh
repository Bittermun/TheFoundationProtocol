#!/bin/bash
# Deploy TFP to Fly.io
# Usage: ./scripts/deploy-fly.sh

set -e

echo "🚀 Deploying TFP to Fly.io..."

# Check prerequisites
if ! command -v fly &> /dev/null; then
    echo "❌ flyctl not found. Install: https://fly.io/docs/hands-on/install-flyctl/"
    exit 1
fi

# Check login
if ! fly auth whoami &> /dev/null; then
    echo "❌ Not logged in. Run: fly auth login"
    exit 1
fi

cd tfp-foundation-protocol

# Copy fly.toml if not exists
if [ ! -f fly.toml ]; then
    echo "📄 Creating fly.toml..."
    cat > fly.toml << 'EOF'
app = 'tfp-demo'
primary_region = 'iad'

[build]
  dockerfile = 'Dockerfile.demo'

[env]
  TFP_MODE = 'demo'
  TFP_DB_PATH = '/data/pib.db'
  NOSTR_RELAY_URL = 'wss://relay.damus.io'

[mounts]
  source = 'tfp_data'
  destination = '/data'

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false
  min_machines_running = 1

  [[http_service.checks]]
    interval = '30s'
    timeout = '5s'
    grace_period = '10s'
    method = 'GET'
    path = '/health'

[[vm]]
  cpu_kind = 'shared'
  cpus = 1
  memory_mb = 512
EOF
fi

# Launch if not already
if ! fly status &> /dev/null; then
    echo "🆕 First-time launch..."
    fly launch --name tfp-demo --region iad --yes

    # Create volume for persistence
    echo "💾 Creating persistent volume..."
    fly volumes create tfp_data --size 1 --region iad --yes || true
else
    echo "🔄 App exists, deploying update..."
fi

# Deploy
echo "🚢 Deploying..."
fly deploy

echo ""
echo "✅ Deployed!"
echo "🌐 URL: https://tfp-demo.fly.dev"
echo "📊 Health: https://tfp-demo.fly.dev/health"
echo "🔧 Admin: https://tfp-demo.fly.dev/admin"
echo ""
echo "To check logs: fly logs"
echo "To SSH in: fly ssh console"
