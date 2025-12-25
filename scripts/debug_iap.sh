#!/bin/bash
set -e

# Configuration
PROJECT_ID="i4g-dev"
REGION="us-central1"
IAP_CLIENT_ID="544936845045-a87u04lgc7go7asc4nhed36ka50iqh0h.apps.googleusercontent.com"
SA_EMAIL="sa-app@i4g-dev.iam.gserviceaccount.com"
API_URL="https://api.intelligenceforgood.org/tasks/debug-test"

echo "--- Debugging IAP Auth ---"
echo "Project: $PROJECT_ID"
echo "SA: $SA_EMAIL"
echo "Audience: $IAP_CLIENT_ID"
echo "URL: $API_URL"

# 1. Get OIDC Token (WITH Email)
echo "Generating OIDC Token (WITH Email)..."
TOKEN_WITH_EMAIL=$(gcloud auth print-identity-token --impersonate-service-account="$SA_EMAIL" --audiences="$IAP_CLIENT_ID" --project="$PROJECT_ID" --include-email)

# 2. Get OIDC Token (WITHOUT Email)
echo "Generating OIDC Token (WITHOUT Email)..."
TOKEN_NO_EMAIL=$(gcloud auth print-identity-token --impersonate-service-account="$SA_EMAIL" --audiences="$IAP_CLIENT_ID" --project="$PROJECT_ID")

# Function to test token
test_token() {
    local name=$1
    local token=$2
    echo -e "\n--- Test: $name ---"
    
    # Decode payload
    echo "Payload:"
    echo "$token" | cut -d. -f2 | base64 -d 2>/dev/null || echo "$token" | cut -d. -f2 | base64 -D 2>/dev/null
    echo ""

    echo "Request (Authorization):"
    curl -s -H "Authorization: Bearer $token" "$API_URL"
}

test_token "With Email" "$TOKEN_WITH_EMAIL"
test_token "Without Email" "$TOKEN_NO_EMAIL"


