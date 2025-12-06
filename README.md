# Meshtastic Relay API

A REST API service for relaying messages to Meshtastic devices via USB or TCP connections. Built with FastAPI, Python 3.11+, and UV package manager.

## Features

- **Dual Connection Support**: Connect via USB serial or TCP/IP
- **Message Queue**: Handles concurrent message requests with a background queue processor
- **Channel Management**: Default channel with optional per-request channel override
- **Message Validation**: Enforces Meshtastic's 200-character message limit
- **Enterprise Quality**: Full type hints, comprehensive logging, and error handling
- **Docker Ready**: Multi-stage Docker build with health checks
- **RESTful API**: Clean FastAPI endpoints with OpenAPI documentation

## Requirements

- Python 3.11 or higher
- UV package manager
- Meshtastic device (connected via USB or accessible via TCP)
- Docker (optional, for containerized deployment)

## Installation

### Using UV (Recommended)

1. Install UV if you haven't already:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Navigate to the project directory:
   ```bash
   cd meshtastic-relay-api
   ```

3. Install dependencies:
   ```bash
   uv pip install -e .
   ```

### Using Docker

1. Build the Docker image:
   ```bash
   docker build -t meshtastic-relay-api .
   ```

2. Or use docker-compose:
   ```bash
   docker-compose up -d
   ```

## Configuration

Configuration is managed through environment variables. Create a `.env` file or set them in your environment:

### Connection Settings

- `CONNECTION_TYPE`: Connection type - `usb` or `tcp` (default: `tcp`)
- `USB_DEVICE`: USB device path (e.g., `/dev/ttyUSB0` or `COM3`) - required for USB
- `TCP_HOST`: TCP hostname or IP address - required for TCP (port is handled automatically by Meshtastic library)

### API Settings

- `API_HOST`: API server host (default: `0.0.0.0`)
- `API_PORT`: API server port (default: `8000`)
- `LOG_LEVEL`: Logging level - `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (default: `INFO`)

### Message Settings

- `MAX_MESSAGE_LENGTH`: Maximum message length in characters (default: `200`)
- `BLACKLISTED_CHANNELS`: Comma-separated list of channel names to blacklist (default: empty). Messages sent to blacklisted channels will be rejected with a 403 Forbidden error.
- `DEBUG_MODE`: Enable debug/dry-run mode (default: `false`). When enabled, messages are logged with detailed channel information but NOT actually sent to the device. Useful for debugging channel index issues.

### Security Settings

- `ENABLE_AUTH`: Enable API key authentication (default: `false` - suitable for trusted environments like airgap networks or homelabs. Set to `true` for production/untrusted networks)
- `API_KEYS`: Comma-separated list of valid API keys (required if `ENABLE_AUTH=true`)
- `RATE_LIMIT_PER_MINUTE`: Rate limit per minute per IP/API key (default: `60`)
- `ENABLE_CORS`: Enable CORS (default: `true`)
- `CORS_ORIGINS`: Comma-separated list of allowed CORS origins (default: `*`)
- `ENABLE_HSTS`: Enable HSTS header (only use with HTTPS, default: `false`)
- `HSTS_MAX_AGE`: HSTS max-age in seconds (default: `31536000`)
- `SANITIZE_LOGS`: Sanitize sensitive data from logs (default: `true`)

**⚠️ Security Note:** See [SECURITY.md](SECURITY.md) for detailed security configuration and best practices.

### Example `.env` file for TCP connection (trusted environment - no auth):

```env
CONNECTION_TYPE=tcp
TCP_HOST=192.168.1.100
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
MAX_MESSAGE_LENGTH=200

# Channel blacklist (optional - prevents sending to these channels)
BLACKLISTED_CHANNELS=LongFast

# Debug mode (optional - enables dry-run mode for debugging)
# DEBUG_MODE=true

# Security settings (authentication disabled for trusted environment)
ENABLE_AUTH=false
RATE_LIMIT_PER_MINUTE=60
ENABLE_CORS=true
CORS_ORIGINS=*
SANITIZE_LOGS=true
```

### Example `.env` file for production (with authentication):

```env
CONNECTION_TYPE=tcp
TCP_HOST=192.168.1.100
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
MAX_MESSAGE_LENGTH=200

# Security settings (authentication enabled)
ENABLE_AUTH=true
API_KEYS=your-secure-api-key-here,another-api-key
RATE_LIMIT_PER_MINUTE=60
ENABLE_CORS=true
CORS_ORIGINS=https://yourdomain.com
SANITIZE_LOGS=true
```

### Example `.env` file for USB connection:

```env
CONNECTION_TYPE=usb
USB_DEVICE=/dev/ttyUSB0
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
MAX_MESSAGE_LENGTH=200
```

## Usage

### Running the API

Using UV (recommended):
```bash
uv run uvicorn meshtastic_relay_api.main:app --host 0.0.0.0 --port 8000
```

Or using the provided script:
```bash
./run.sh
```

Or using Make:
```bash
make run
```

Or using the module directly (if dependencies are installed in your Python environment):
```bash
python -m meshtastic_relay_api.main
```

### API Endpoints

#### Health Check

```bash
GET /health
```

Returns the health status of the service, including connection status and queue size.

**Response:**
```json
{
  "status": "healthy",
  "connected": true,
  "connection_type": "tcp",
  "queue_size": 0
}
```

#### Send Message

```bash
POST /message
Content-Type: application/json

{
  "message": "Hello from the API!",
  "channel": "LongFast"  // Required - channel name must be specified
}
```

Sends a message to the Meshtastic device. The `channel` parameter is **required** and must be specified for each message.

**Response:**
```json
{
  "success": true,
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Hello from the API!",
  "channel": "LongFast",
  "queue_position": 1
}
```

#### Queue Status

```bash
GET /queue/status
```

Returns the current status of the message queue.

**Response:**
```json
{
  "queue_size": 5,
  "processing": true
}
```

### Sending Test Messages

#### Quick Test Script

The easiest way to send a test message:

```bash
# Send a message (channel is required)
./send_message.sh -c "LongFast" "Hello from the command line!"

# Send to a different channel
./send_message.sh -c "ShortFast" "Test message"

# Send to a different API URL
./send_message.sh --url http://localhost:8000 "Hello World"
```

#### Using the Test Script

You can also use the test script to send a single message:

```bash
# Send test message (channel is required)
./test_api.sh --send -m "My custom message" -c "LongFast"

# Send to different channel
./test_api.sh --send -m "Test" -c "ShortFast"
```

### API Documentation

Once the server is running, visit:
- **Swagger UI**: `http://localhost:8000/docs` - Interactive API documentation with "Try it out" feature
- **ReDoc**: `http://localhost:8000/redoc` - Beautiful, responsive API documentation
- **OpenAPI JSON**: `http://localhost:8000/openapi.json` - OpenAPI specification in JSON format
- **OpenAPI YAML**: `http://localhost:8000/openapi.yaml` - OpenAPI specification in YAML format (requires pyyaml)

#### Exporting OpenAPI Specification

You can export the OpenAPI specification to files using the provided script:

```bash
# Install pyyaml if not already installed
pip install pyyaml

# Export to both JSON and YAML
python export_openapi.py
```

This will create:
- `openapi.json` - OpenAPI specification in JSON format
- `openapi.yaml` - OpenAPI specification in YAML format

The OpenAPI spec includes:
- Complete endpoint documentation with examples
- Request/response schemas
- Authentication requirements
- Error responses
- Query parameters and their descriptions
- Comprehensive feature descriptions

## Docker Deployment

### Building and Pushing to DockerHub

The easiest way to build and publish to DockerHub:

```bash
# Using the publish script (recommended)
./docker-publish.sh

# Or using Make
make docker-build-push

# Or manually
make docker-build
make docker-push
```

The script will:
- Build the Docker image
- Extract version from `pyproject.toml`
- Tag with both `latest` and version tag
- Push to `martinoj2009/meshtastic-relay-api` on DockerHub

**Prerequisites:**
- Docker must be installed and running
- You must be logged into DockerHub: `docker login`

**Manual build and push:**
```bash
docker build -t martinoj2009/meshtastic-relay-api:latest .
docker tag martinoj2009/meshtastic-relay-api:latest martinoj2009/meshtastic-relay-api:1.0.0
docker push martinoj2009/meshtastic-relay-api:latest
docker push martinoj2009/meshtastic-relay-api:1.0.0
```

### Running with Docker

For TCP connection:
```bash
docker run -d \
  --name meshtastic-relay-api \
  -p 8000:8000 \
  -e CONNECTION_TYPE=tcp \
  -e TCP_HOST=192.168.1.100 \
  martinoj2009/meshtastic-relay-api:latest
```

For USB connection:
```bash
docker run -d \
  --name meshtastic-relay-api \
  -p 8000:8000 \
  --device=/dev/ttyUSB0 \
  -e CONNECTION_TYPE=usb \
  -e USB_DEVICE=/dev/ttyUSB0 \
  martinoj2009/meshtastic-relay-api:latest
```

**Pull the image:**
```bash
docker pull martinoj2009/meshtastic-relay-api:latest
```

## Architecture

### Components

1. **MeshtasticManager**: Manages the connection to the Meshtastic device (USB or TCP)
2. **MessageQueue**: Thread-safe queue with background processor for handling concurrent requests
3. **FastAPI Application**: REST API endpoints with request validation and error handling
4. **Configuration**: Pydantic-based settings management with environment variable support

### Message Flow

1. Client sends POST request to `/message` endpoint
2. Request is validated (message length, format)
3. Message is enqueued with unique ID
4. Background processor picks up message from queue
5. MeshtasticManager sends message to device
6. Response returned to client with message ID and queue position

## Testing

### API Integration Tests

A comprehensive test script is provided to test all API endpoints:

```bash
# Run all API tests
./test_api.sh

# Run with verbose output
./test_api.sh --verbose

# Test against different API URL
./test_api.sh --url http://localhost:8000

# Or using Make
make test-api
```

The test script will:
- Check if the API is running
- Test all endpoints (root, health, queue status, send message)
- Test error cases (message too long, invalid JSON, etc.)
- Test multiple messages and queue processing
- Test different channels
- Provide a summary of test results

### Development

### Setting up development environment

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run linters
ruff check src/
black src/
mypy src/

# Run tests (when available)
pytest

# Run API integration tests
make test-api
```

### Project Structure

```
meshtastic-relay-api/
├── src/
│   └── meshtastic_relay_api/
│       ├── __init__.py
│       ├── main.py           # FastAPI application
│       ├── config.py          # Configuration management
│       ├── models.py          # Pydantic models
│       ├── meshtastic_manager.py  # Device connection manager
│       └── message_queue.py   # Message queue processor
├── pyproject.toml             # UV project configuration
├── Dockerfile                 # Docker build configuration
├── docker-compose.yml         # Docker Compose configuration
├── docker-publish.sh         # Build and publish to DockerHub script
├── test_api.sh                # API integration test script
├── send_message.sh            # Simple script to send a test message
├── run.sh                     # Quick start script
├── Makefile                   # Convenience commands
└── README.md                  # This file
```

## Troubleshooting

### Connection Issues

- **USB**: Ensure the device path is correct and the user has permissions to access it
- **TCP**: Verify the device is on the network and TCP server is enabled in Meshtastic settings
- Check logs for detailed error messages

### Message Queue Issues

- Monitor queue size via `/queue/status` endpoint
- If queue grows large, check if device is connected via `/health` endpoint
- Messages will retry up to 3 times before being dropped

### Channel Not Found

- Verify channel name matches exactly (case-sensitive)
- Check available channels on your Meshtastic device
- **Important**: If a channel name is not found, the message will be rejected and NOT sent to the default channel (index 0)
- Use `DEBUG_MODE=true` to see all available channels and their indices
- Channel names are case-sensitive and must match exactly as configured on the device

### Channel Blacklisted

- If you receive a 403 Forbidden error saying a channel is blacklisted, check your `BLACKLISTED_CHANNELS` configuration
- Channel blacklist matching is case-insensitive
- To remove a channel from the blacklist, remove it from the `BLACKLISTED_CHANNELS` environment variable and restart the API

### Debug Mode

- Enable `DEBUG_MODE=true` to see detailed channel information without sending messages
- In debug mode, the API will:
  - List all available channels on the device with their indices
  - Show which channel index will be used for each message
  - Log message details without actually sending
  - Help identify channel index mismatches
- Set `LOG_LEVEL=DEBUG` for even more detailed output

## License

This project is provided as-is for use in your scripts repository.

## Contributing

This is a monorepo project. Please ensure all changes are tested and follow the existing code style.

