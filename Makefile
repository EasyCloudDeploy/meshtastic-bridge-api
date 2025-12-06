.PHONY: help install run test test-api lint format clean docker-build docker-run docker-push docker-build-push

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies using UV
	uv pip install -e .

install-dev: ## Install dependencies with dev tools
	uv pip install -e ".[dev]"

run: ## Run the API server
	uv run uvicorn meshtastic_relay_api.main:app --host 0.0.0.0 --port 8000 --reload

lint: ## Run linters
	ruff check src/
	mypy src/

format: ## Format code
	black src/
	ruff check --fix src/

test: ## Run tests (when available)
	pytest

test-api: ## Run API integration tests
	./test_api.sh

clean: ## Clean build artifacts
	rm -rf __pycache__ .pytest_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

docker-build: ## Build Docker image
	docker build -t meshtastic-relay-api:latest .

docker-run: ## Run Docker container (TCP connection)
	docker run -d \
		--name meshtastic-relay-api \
		-p 8000:8000 \
		-e CONNECTION_TYPE=tcp \
		-e TCP_HOST=192.168.1.100 \
		meshtastic-relay-api:latest

docker-run-usb: ## Run Docker container (USB connection)
	docker run -d \
		--name meshtastic-relay-api \
		-p 8000:8000 \
		--device=/dev/ttyUSB0 \
		-e CONNECTION_TYPE=usb \
		-e USB_DEVICE=/dev/ttyUSB0 \
		meshtastic-relay-api:latest

docker-push: ## Push Docker image to DockerHub (uses docker-publish.sh)
	./docker-publish.sh

docker-build-push: docker-build docker-push ## Build and push Docker image to DockerHub

