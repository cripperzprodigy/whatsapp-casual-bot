#!/bin/bash

# Configuration
GATEWAY_URL="http://localhost:3000"
TEST_NUMBER="1234567890@s.whatsapp.net" # Dummy number for testing the endpoint response logic

echo "=== WhatsApp Gateway Connection Test ==="

# 1. Check if Node.js service is running
echo "Checking if Node.js service is reachable at $GATEWAY_URL..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GATEWAY_URL/whatsapp/status")

if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Node.js service is not reachable (HTTP Code: $HTTP_CODE). Please start it first."
else
    echo "✅ Node.js service is running."

    # 2. Call /whatsapp/status endpoint
    echo -e "\n--- Status Endpoint ---"
    curl -s "$GATEWAY_URL/whatsapp/status" | jq .

    # 3. Call /whatsapp/connection-info
    echo -e "\n--- Connection Info Endpoint ---"
    curl -s "$GATEWAY_URL/whatsapp/connection-info" | jq .

    # 4. Attempt to send a test message
    echo -e "\n--- Sending Test Message ---"
    PAYLOAD=$(cat <<JSON_PAYLOAD
{
  "number": "$TEST_NUMBER",
  "textMessage": {
    "text": "This is a test message from the validation script."
  }
}
JSON_PAYLOAD
)

    curl -s -X POST "$GATEWAY_URL/message/sendText" \
         -H "Content-Type: application/json" \
         -d "$PAYLOAD" | jq .
fi

echo -e "\n=== Test Complete ==="
