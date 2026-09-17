#!/bin/bash
# LTX Lab Launcher
# Single command to start the full lab experience:
# - MLflow UI (traces, experiments, nested inference spans)
# - Streamlit WebUI (Generate, Traces, Observability, Library, Info)
# - Observability stack (Prometheus + Grafana + Loki)

set -e

echo "=== LTX Lab Launcher ==="
echo "Starting MLflow, Streamlit web UI, and observability stack..."
echo ""

# Ensure we're in the project root
cd "$(dirname "$0")"

# 1. Start observability stack (Prometheus, Grafana, Loki) in background
echo "→ Starting observability stack (Grafana on :3000, Prometheus on :9090)..."
(cd observability && docker compose up -d --quiet-pull)

# 2. Start MLflow UI (traces + experiment tracking)
echo "→ Starting MLflow UI on http://localhost:5000 ..."
mlflow ui --port 5000 --host 0.0.0.0 > /tmp/mlflow.log 2>&1 &
MLFLOW_PID=$!

# 3. Start Streamlit WebUI (the main lab interface with all instructions)
echo "→ Starting LTX Lab Web UI on http://localhost:8501 ..."
echo ""
echo "All instructions, generation controls, MLflow traces, and observability dashboards are now inside the UI."
echo "Open the link below and explore the sidebar."
echo ""

# Use the venv from LTX-2 (contains streamlit + mlflow)
LTX_VENV="./LTX-2/.venv/bin/python"

if [ -f "$LTX_VENV" ]; then
  # Set MLflow tracking to local directory for persistence
  export MLFLOW_TRACKING_URI="file://$(pwd)/mlruns"
  echo "MLflow tracking URI set to: $MLFLOW_TRACKING_URI"
  echo "MLflow UI: http://localhost:5000"
  echo "Streamlit Lab: http://localhost:8501"
  echo ""
  cd webui
  "$LTX_VENV" -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
else
  echo "Error: LTX-2 venv not found. Please run ./setup-ltx-macos.sh first."
  exit 1
fi

# Cleanup on exit (best effort)
trap 'kill $MLFLOW_PID 2>/dev/null || true; (cd ../observability && docker compose down)' EXIT
