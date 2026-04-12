#!/bin/bash
# Run the Polymarket Bot Dashboard

cd "$(dirname "$0")/../.."

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "⚠ Virtual environment not found. Creating one..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Check if Flask is installed
if ! python -c "import flask" 2>/dev/null; then
    echo "📦 Installing Flask and dependencies..."
    pip install flask flask-cors -q
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🤖 Polymarket Bot Dashboard"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Start dashboard
python scripts/dashboard/app.py &

DASHBOARD_PID=$!

sleep 2

echo ""
echo "✓ Dashboard starting..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Dashboard URL: http://localhost:5000"
echo "  API Status:    http://localhost:5000/api/status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Wait for Ctrl+C
trap "kill $DASHBOARD_PID 2>/dev/null; echo ''; echo 'Dashboard stopped.'; exit 0" INT

wait $DASHBOARD_PID
