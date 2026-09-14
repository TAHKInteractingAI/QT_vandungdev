#!/usr/bin/env bash
set -e

echo "=== 1. RUNNING PYTEST (AUTOMATED UNIT & INTEGRATION TESTS) ==="
uv run pytest tests/automated/ -v

echo ""
echo "=== 2. LAUNCHING LOCAL FASTAPI SERVER IN BACKGROUND ==="
uv run python main.py > /tmp/fastapi_test.log 2>&1 &
SERVER_PID=$!
echo "-> Server PID: $SERVER_PID"

cleanup() {
    echo "-> Stopping FastAPI Server (PID: $SERVER_PID)..."
    kill $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

echo "-> Waiting for server to become healthy..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/health > /dev/null; then
        echo "-> Server is ready!"
        break
    fi
    sleep 0.5
done

echo ""
echo "=== 3. RUNNING CRON-JOB.ORG MOCK SIMULATION SCRIPT (HTTP/E2E) ==="
uv run python tests/http/mock_cron_job.py

echo ""
echo "🎉 ALL LOCAL TEST STEPS COMPLETED SUCCESSFULLY!"
echo "📁 List of generated Excel files in tests/output/:"
ls -lh tests/output/
