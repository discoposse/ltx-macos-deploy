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
echo "   (Stopping any old conflicting containers first to avoid port conflicts)"
(cd observability && docker compose down --remove-orphans 2>/dev/null || true)

# Also stop any unrelated containers that may be using common dev ports (e.g. 8080 from other projects)
docker stop rackn-competitour-auth 2>/dev/null || true
docker rm rackn-competitour-auth 2>/dev/null || true

(cd observability && docker compose up -d --quiet-pull)

# 2. Start MLflow UI (traces + experiment tracking)
echo "→ Starting MLflow UI on http://localhost:5001 ..."
MLFLOW_BIN="./LTX-2/.venv/bin/mlflow"
if [ -x "$MLFLOW_BIN" ]; then
  # Kill any existing process on port 5001
  lsof -ti:5001 | xargs kill -9 2>/dev/null || true
  sleep 1

  # Use port 5001 to avoid macOS ControlCenter conflict on port 5000
  "$MLFLOW_BIN" ui --port 5001 --host 0.0.0.0 --allowed-hosts localhost,127.0.0.1,0.0.0.0 > /tmp/mlflow.log 2>&1 &
  MLFLOW_PID=$!
  echo "MLflow started with PID $MLFLOW_PID on port 5001"
else
  echo "Warning: mlflow not found in venv. Install with: cd LTX-2 && uv sync --group dev"
  MLFLOW_PID=0
fi

# 3. Start Streamlit WebUI (the main lab interface with all instructions)
echo "→ Starting LTX Lab Web UI on http://localhost:8501 ..."
echo ""
echo "All instructions, generation controls, MLflow traces, and observability dashboards are now inside the UI."
echo "Open the link below and explore the sidebar."
echo ""

# Use the venv from LTX-2 (contains streamlit + mlflow)
# Resolve project root correctly (dirname $0 may be LTX-2 when run from inside it)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
VENV_STREAMLIT="$PROJECT_ROOT/LTX-2/.venv/bin/streamlit"

echo "Debug: Using PROJECT_ROOT=$PROJECT_ROOT"
echo "Debug: Looking for streamlit at $VENV_STREAMLIT"
ls -la "$VENV_STREAMLIT" 2>&1 | cat

if [ -x "$VENV_STREAMLIT" ]; then
  # Set MLflow tracking to local directory for persistence
  export MLFLOW_TRACKING_URI="file://$(pwd)/mlruns"
  echo "MLflow tracking URI set to: $MLFLOW_TRACKING_URI"
  echo "MLflow UI: http://localhost:5001"
  echo "Streamlit Lab: http://localhost:8501"
  echo ""
  cd webui
  echo "Launching with: $VENV_STREAMLIT"
  "$VENV_STREAMLIT" run app.py --server.port 8501 --server.address 0.0.0.0
else
  echo "Error: Streamlit not found in LTX-2 venv."
  echo "Tried: $VENV_STREAMLIT"
  echo "Please run: cd LTX-2 && uv sync --group dev"
  echo "Then try ./start-lab.sh again from the project root."
  exit 1
fi

# Cleanup on exit (best effort)
trap 'kill $MLFLOW_PID 2>/dev/null || true; (cd observability && docker compose down --remove-orphans)' EXIT
