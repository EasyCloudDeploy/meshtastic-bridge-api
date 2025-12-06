#!/bin/bash
# Test script for Meshtastic Relay API
# Tests all endpoints with various scenarios

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
API_URL="${API_URL:-http://localhost:8000}"
VERBOSE="${VERBOSE:-false}"

# Counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_test() {
    echo -e "${YELLOW}Testing: $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
    ((TESTS_PASSED++))
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
    ((TESTS_FAILED++))
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if API is running
check_api_running() {
    local exit_on_fail="${1:-true}"
    
    if [ "$exit_on_fail" != "false" ]; then
        print_header "Checking if API is running"
    fi
    
    if curl -s -f "${API_URL}/health" > /dev/null 2>&1; then
        if [ "$exit_on_fail" != "false" ]; then
            print_success "API is running at ${API_URL}"
        fi
        return 0
    else
        print_error "API is not running at ${API_URL}"
        echo "Please start the API first:"
        echo "  ./run.sh"
        echo "  or"
        echo "  make run"
        if [ "$exit_on_fail" != "false" ]; then
            exit 1
        else
            return 1
        fi
    fi
}

# Test root endpoint
test_root() {
    print_header "Testing Root Endpoint"
    
    print_test "GET /"
    response=$(curl -s -w "\n%{http_code}" "${API_URL}/")
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ]; then
        print_success "Root endpoint returned 200"
        if [ "$VERBOSE" = "true" ]; then
            echo "$body" | jq '.' 2>/dev/null || echo "$body"
        fi
    else
        print_error "Root endpoint returned $http_code"
    fi
}

# Test health endpoint
test_health() {
    print_header "Testing Health Endpoint"
    
    print_test "GET /health"
    response=$(curl -s -w "\n%{http_code}" "${API_URL}/health")
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ]; then
        print_success "Health endpoint returned 200"
        if [ "$VERBOSE" = "true" ]; then
            echo "$body" | jq '.' 2>/dev/null || echo "$body"
        fi
        
        # Check if connected
        if command -v jq &> /dev/null; then
            connected=$(echo "$body" | jq -r '.connected // false')
            status=$(echo "$body" | jq -r '.status // "unknown"')
            queue_size=$(echo "$body" | jq -r '.queue_size // 0')
            
            print_info "Status: $status"
            print_info "Connected: $connected"
            print_info "Queue size: $queue_size"
        fi
    else
        print_error "Health endpoint returned $http_code"
    fi
}

# Test queue status endpoint
test_queue_status() {
    print_header "Testing Queue Status Endpoint"
    
    print_test "GET /queue/status"
    response=$(curl -s -w "\n%{http_code}" "${API_URL}/queue/status")
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "200" ]; then
        print_success "Queue status endpoint returned 200"
        if [ "$VERBOSE" = "true" ]; then
            echo "$body" | jq '.' 2>/dev/null || echo "$body"
        fi
        
        if command -v jq &> /dev/null; then
            queue_size=$(echo "$body" | jq -r '.queue_size // 0')
            processing=$(echo "$body" | jq -r '.processing // false')
            print_info "Queue size: $queue_size"
            print_info "Processing: $processing"
        fi
    else
        print_error "Queue status endpoint returned $http_code"
    fi
}

# Test sending a message
test_send_message() {
    print_header "Testing Send Message Endpoint"
    
    local message="$1"
    local channel="$2"
    local expected_status="${3:-202}"
    
    print_test "POST /message (message: '${message:0:30}...', channel: ${channel:-default})"
    
    # Build JSON payload
    if [ -n "$channel" ]; then
        json_payload=$(jq -n \
            --arg msg "$message" \
            --arg ch "$channel" \
            '{message: $msg, channel: $ch}')
    else
        json_payload=$(jq -n \
            --arg msg "$message" \
            '{message: $msg}')
    fi
    
    response=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "$json_payload" \
        "${API_URL}/message")
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" = "$expected_status" ]; then
        print_success "Send message returned $http_code"
        if [ "$VERBOSE" = "true" ]; then
            echo "$body" | jq '.' 2>/dev/null || echo "$body"
        fi
        
        if command -v jq &> /dev/null && [ "$http_code" = "202" ]; then
            message_id=$(echo "$body" | jq -r '.message_id // "N/A"')
            queue_position=$(echo "$body" | jq -r '.queue_position // "N/A"')
            print_info "Message ID: $message_id"
            print_info "Queue position: $queue_position"
        fi
    else
        print_error "Send message returned $http_code (expected $expected_status)"
        if [ "$VERBOSE" = "true" ]; then
            echo "$body" | jq '.' 2>/dev/null || echo "$body"
        fi
    fi
}

# Test sending multiple messages
test_send_multiple_messages() {
    print_header "Testing Multiple Messages"
    
    print_info "Sending 5 messages in quick succession..."
    
    for i in {1..5}; do
        test_send_message "Test message #$i from API test script" ""
        sleep 0.5
    done
    
    print_info "Waiting 2 seconds for queue to process..."
    sleep 2
    
    # Check queue status
    test_queue_status
}

# Test error cases
test_error_cases() {
    print_header "Testing Error Cases"
    
    # Test message too long
    print_test "POST /message (message too long - 201 chars)"
    long_message=$(printf 'a%.0s' {1..201})
    test_send_message "$long_message" "" "400"
    
    # Test empty message
    print_test "POST /message (empty message)"
    test_send_message "" "" "422"
    
    # Test invalid JSON
    print_test "POST /message (invalid JSON)"
    response=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{"message":}' \
        "${API_URL}/message")
    http_code=$(echo "$response" | tail -n1)
    
    if [ "$http_code" = "422" ] || [ "$http_code" = "400" ]; then
        print_success "Invalid JSON correctly rejected ($http_code)"
    else
        print_error "Invalid JSON returned $http_code (expected 422 or 400)"
    fi
    
    # Test missing message field
    print_test "POST /message (missing message field)"
    response=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d '{"channel": "J Sec Chan"}' \
        "${API_URL}/message")
    http_code=$(echo "$response" | tail -n1)
    
    if [ "$http_code" = "422" ]; then
        print_success "Missing message field correctly rejected (422)"
    else
        print_error "Missing message field returned $http_code (expected 422)"
    fi
}

# Test different channels
test_different_channels() {
    print_header "Testing Different Channels"
    
    # Test with default channel (no channel specified)
    print_info "Testing with default channel..."
    test_send_message "Test message with default channel" ""
    
    # Test with explicit channel (example - user can modify)
    print_info "Testing with explicit channel (example)..."
    test_send_message "Test message with explicit channel" "ShortFast"
}

# Test API documentation endpoints
test_docs() {
    print_header "Testing API Documentation Endpoints"
    
    print_test "GET /docs"
    response=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/docs")
    if [ "$response" = "200" ]; then
        print_success "Swagger UI available at ${API_URL}/docs"
    else
        print_error "Swagger UI returned $response"
    fi
    
    print_test "GET /redoc"
    response=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/redoc")
    if [ "$response" = "200" ]; then
        print_success "ReDoc available at ${API_URL}/redoc"
    else
        print_error "ReDoc returned $response"
    fi
    
    print_test "GET /openapi.json"
    response=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/openapi.json")
    if [ "$response" = "200" ]; then
        print_success "OpenAPI schema available at ${API_URL}/openapi.json"
    else
        print_error "OpenAPI schema returned $response"
    fi
}

# Send a single test message (simple function for quick testing)
send_test_message() {
    local message="${1:-Test message from API}"
    local channel="${2:-}"
    
    print_header "Sending Test Message"
    
    print_info "Message: $message"
    if [ -z "$channel" ]; then
        print_info "Channel: (using API default)"
    else
        print_info "Channel: $channel"
    fi
    
    test_send_message "$message" "$channel"
    
    echo ""
    print_info "Message sent! Check your Meshtastic device."
}

# Print summary
print_summary() {
    print_header "Test Summary"
    
    total_tests=$((TESTS_PASSED + TESTS_FAILED))
    echo "Total tests: $total_tests"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    
    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "\n${GREEN}All tests passed!${NC}"
        exit 0
    else
        echo -e "\n${RED}Some tests failed.${NC}"
        exit 1
    fi
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════╗"
    echo "║  Meshtastic Relay API Test Suite       ║"
    echo "╚════════════════════════════════════════╝"
    echo -e "${NC}"
    
    echo "API URL: ${API_URL}"
    echo "Verbose: ${VERBOSE}"
    echo ""
    
    # Check if jq is available (optional but recommended)
    if ! command -v jq &> /dev/null; then
        print_info "jq not found. Install it for better JSON output: brew install jq"
    fi
    
    # Run tests
    check_api_running
    test_root
    test_health
    test_queue_status
    test_docs
    test_send_message "Hello from the API test script!" ""
    test_send_message "Another test message" ""
    test_different_channels
    test_send_multiple_messages
    test_error_cases
    
    # Print summary
    print_summary
}

# Parse command line arguments
SEND_MESSAGE=""
MESSAGE_TEXT=""
CHANNEL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--url)
            API_URL="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="true"
            shift
            ;;
        -s|--send)
            SEND_MESSAGE="true"
            shift
            ;;
        -m|--message)
            MESSAGE_TEXT="$2"
            shift 2
            ;;
        -c|--channel)
            CHANNEL="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -u, --url URL        API URL (default: http://localhost:8000)"
            echo "  -v, --verbose        Enable verbose output"
            echo "  -s, --send           Send a single test message"
            echo "  -m, --message TEXT   Message text to send (use with -s)"
            echo "  -c, --channel NAME   Channel name (optional, uses API default if not specified)"
            echo "  -h, --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Run full test suite"
            echo "  $0 --send                            # Send default test message"
            echo "  $0 --send --message 'Hello World'    # Send custom message"
            echo "  $0 --send -m 'Test' -c 'ShortFast'   # Send to specific channel"
            echo "  $0 --url http://localhost:8000 --verbose"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# If --send flag is set, just send a message and exit
if [ "$SEND_MESSAGE" = "true" ]; then
    if ! check_api_running false; then
        exit 1
    fi
    send_test_message "${MESSAGE_TEXT:-Test message from API}" "$CHANNEL"
    exit 0
fi

# Run main function
main

