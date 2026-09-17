#!/bin/bash
# LTX Lab Stop Script
# Stops all components of the LTX Lab cleanly

echo "=== Stopping LTX Lab ==="

# Kill Gradio / web UI
echo "→ Stopping Gradio web UI (port 8501)..."
lsof -ti:8501 | xargs kill -9 2>/dev/null || true

# Kill MLflow
echo "→ Stopping MLflow UI (port 5001)..."
lsof -ti:5001 | xargs kill -9 2>/dev/null || true

# Stop observability stack
echo "→ Stopping observability stack (Grafana, Prometheus, Loki)..."
(cd observability && docker compose down --remove-orphans 2>/dev/null || true)

echo ""
echo "LTX Lab stopped."
echo "Run './start-lab.sh' to start it again."
