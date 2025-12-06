#!/bin/bash
# Simple script to send a test message to Meshtastic Relay API

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
API_URL="${API_URL:-http://localhost:8000}"

# Parse arguments
MESSAGE=""
CHANNEL=""
MESSAGE_PARTS=()

show_help() {
    echo "Usage: $0 [OPTIONS] -c CHANNEL MESSAGE"
    echo ""
    echo "Send a message to the Meshtastic Relay API"
    echo ""
    echo "Options:"
    echo "  -c, --channel NAME Channel name (required)"
    echo "  -u, --url URL      API URL (default: http://localhost:8000)"
    echo "  -h, --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 -c 'LongFast' 'Hello from the command line!'"
    echo "  $0 -u http://127.0.0.1:8000 -c 'JSecChannel' 'Test message'"
    echo "  $0 --channel 'ShortFast' --url http://localhost:8000 'Hello World'"
    exit 0
}

# First pass: collect all flags and their values
while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--url)
            if [ -z "$2" ]; then
                echo -e "${RED}Error: -u/--url requires a value${NC}"
                exit 1
            fi
            API_URL="$2"
            shift 2
            ;;
        -c|--channel)
            if [ -z "$2" ]; then
                echo -e "${RED}Error: -c/--channel requires a value${NC}"
                exit 1
            fi
            CHANNEL="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
        *)
            # Collect all non-flag arguments as message parts
            MESSAGE_PARTS+=("$1")
            shift
            ;;
    esac
done

# Join message parts with spaces
MESSAGE="${MESSAGE_PARTS[*]}"

# Validate channel
if [ -z "$CHANNEL" ]; then
    echo -e "${RED}Error: Channel is required${NC}"
    echo "Use -c or --channel to specify the channel name"
    echo ""
    show_help
    exit 1
fi

# Validate message
if [ -z "$MESSAGE" ]; then
    echo -e "${RED}Error: Message is required${NC}"
    echo ""
    show_help
    exit 1
fi

# Check if API is running
echo -e "${YELLOW}Checking API connection...${NC}"
if ! curl -s -f "${API_URL}/health" > /dev/null 2>&1; then
    echo -e "${RED}Error: API is not running at ${API_URL}${NC}"
    echo "Please start the API first:"
    echo "  ./run.sh"
    echo "  or"
    echo "  make run"
    exit 1
fi

# Build JSON payload
json_payload=$(jq -n \
    --arg msg "$MESSAGE" \
    --arg ch "$CHANNEL" \
    '{message: $msg, channel: $ch}' 2>/dev/null || \
    echo "{\"message\": \"$MESSAGE\", \"channel\": \"$CHANNEL\"}")

# Send message
echo -e "${YELLOW}Sending message...${NC}"
echo -e "  Message: ${GREEN}$MESSAGE${NC}"
echo -e "  Channel: ${GREEN}$CHANNEL${NC}"

# Debug: show the JSON payload being sent
if [ "$VERBOSE" = "true" ] || [ "${DEBUG:-false}" = "true" ]; then
    echo -e "${YELLOW}Debug - JSON payload:${NC}"
    echo "$json_payload" | jq '.' 2>/dev/null || echo "$json_payload"
fi

response=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "$json_payload" \
    "${API_URL}/message")

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" = "202" ]; then
    echo -e "${GREEN}✓ Message sent successfully!${NC}"
    
    if command -v jq &> /dev/null; then
        message_id=$(echo "$body" | jq -r '.message_id // "N/A"')
        queue_position=$(echo "$body" | jq -r '.queue_position // "N/A"')
        echo -e "  Message ID: ${GREEN}$message_id${NC}"
        echo -e "  Queue position: ${GREEN}$queue_position${NC}"
    fi
else
    echo -e "${RED}✗ Failed to send message (HTTP $http_code)${NC}"
    if command -v jq &> /dev/null; then
        error=$(echo "$body" | jq -r '.error // .detail // "Unknown error"')
        echo -e "  Error: ${RED}$error${NC}"
    else
        echo "$body"
    fi
    exit 1
fi

