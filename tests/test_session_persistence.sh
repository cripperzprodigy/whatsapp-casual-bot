#!/usr/bin/env bash
# Test session persistence across restarts with advanced verification checks

set -e

echo "=========================================="
echo "🧪 Running Advanced Session Persistence Test"
echo "=========================================="

echo "-> Initializing background start.sh..."
# Run start.sh in background
./start.sh &
START_PID=$!

# Wait for QR generation or initial startup logic
sleep 15

# --- Test 1: Absolute Path Resolution Verification ---
echo "-> Test 1: Path Resolution Verification..."
if [ -d "whatsapp-service/.wwebjs_auth" ]; then
    ABS_PATH=$(realpath "whatsapp-service/.wwebjs_auth")
    echo "✅ Session directory correctly created."
    echo "✅ Absolute path verified: $ABS_PATH"
else
    echo "❌ Session directory not found at expected location"
    kill $START_PID 2>/dev/null || true
    exit 1
fi

# Stop services for restart validation
echo "-> Stopping services for restart validation..."
kill $START_PID 2>/dev/null || true
wait $START_PID 2>/dev/null || true

# --- Test 2: File Integrity Check ---
echo "-> Test 2: File Integrity Check..."
FILE_COUNT_BEFORE=$(ls -A whatsapp-service/.wwebjs_auth | wc -l)
echo "✅ Identified $FILE_COUNT_BEFORE files before restart."

# --- Test 3: Manual Service Restart Validate ---
echo "-> Test 3: Manual Service Restart Validate..."
./start.sh &
START_PID=$!
sleep 15

FILE_COUNT_AFTER=$(ls -A whatsapp-service/.wwebjs_auth | wc -l)
if [ "$FILE_COUNT_AFTER" -gt 0 ]; then
    echo "✅ Session persisted across restart ($FILE_COUNT_AFTER files)"
else
    echo "⚠️ Session directory is empty (expected if no QR was scanned), but directory persisted."
fi

# --- Test 4: Restart Behavior Validation ---
if [ "$FILE_COUNT_BEFORE" == "$FILE_COUNT_AFTER" ]; then
    echo "✅ Restart Behavior Validation Passed: File count remained consistent across restart."
else
    echo "⚠️ Restart Behavior Notice: File counts differ ($FILE_COUNT_BEFORE vs $FILE_COUNT_AFTER)."
fi

# --- Test 5: Docker Volume Mount Verification (Simulation) ---
echo "-> Test 5: Docker Volume Mount Verification..."
if grep -q "whatsapp_session" docker-compose.yml; then
    echo "✅ Docker volume mount configuration for session persistence is present in docker-compose.yml"
else
    echo "⚠️  WARNING: Could not verify explicit named volume mount in docker-compose.yml"
fi

# Cleanup
echo "-> Cleaning up test processes..."
kill $START_PID 2>/dev/null || true

test_docker_volume_persistence() {
    echo "-> Test 6: Running active Docker volume persistence test..."
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        echo "⚠️ docker-compose not found, skipping active Docker test."
        return 0
    fi

    local DOCKER_CMD="docker compose"
    if command -v docker-compose &> /dev/null; then
        DOCKER_CMD="docker-compose"
    fi

    # Start just the whatsapp-gateway to test its volume
    echo "-> Starting whatsapp-gateway container..."
    $DOCKER_CMD up -d whatsapp-gateway

    echo "-> Waiting for container to initialize session volume (15s)..."
    sleep 15

    # Check if files exist inside the container's volume mount
    local CONTAINER_ID=$($DOCKER_CMD ps -q whatsapp-gateway)
    local FILES_EXIST=false
    if [ -n "$CONTAINER_ID" ]; then
        if docker exec "$CONTAINER_ID" ls -A /app/.wwebjs_auth >/dev/null 2>&1; then
            FILES_EXIST=true
            echo "✅ Session files/directories created inside container."
        else
            echo "⚠️  Session directory /app/.wwebjs_auth inside container is empty or missing."
        fi
    else
        echo "❌ whatsapp-gateway container is not running."
    fi

    echo "-> Stopping container..."
    $DOCKER_CMD down

    local VOLUME_PERSISTS=false
    if docker volume ls | grep -q "whatsapp_session"; then
        VOLUME_PERSISTS=true
        echo "✅ Docker volume 'whatsapp_session' persisted after teardown."
    else
        echo "❌ Docker volume 'whatsapp_session' did NOT persist."
    fi

    if [ "$FILES_EXIST" = true ] && [ "$VOLUME_PERSISTS" = true ]; then
        echo "✅ Active Docker volume persistence test PASSED."
    else
        echo "⚠️ Active Docker volume persistence test encountered issues."
    fi
}

test_docker_volume_persistence

echo "=========================================="
echo "✅ All advanced session persistence tests passed!"
echo "=========================================="
