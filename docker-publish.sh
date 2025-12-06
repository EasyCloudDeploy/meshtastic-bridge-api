#!/bin/bash
# Build and publish Meshtastic Relay API to DockerHub

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
DOCKER_REPO="martinoj2009/meshtastic-relay-api"
IMAGE_NAME="meshtastic-relay-api"

# Get version from pyproject.toml
VERSION=$(grep -E '^version\s*=' pyproject.toml | sed -E 's/^version\s*=\s*"([^"]+)".*/\1/' || echo "latest")

if [ "$VERSION" = "latest" ]; then
    echo -e "${YELLOW}Warning: Could not determine version from pyproject.toml, using 'latest'${NC}"
fi

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Docker Build & Publish Script       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "Repository: ${GREEN}${DOCKER_REPO}${NC}"
echo -e "Version:    ${GREEN}${VERSION}${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check if logged into DockerHub
if ! docker info | grep -q "Username"; then
    echo -e "${YELLOW}Warning: Not logged into DockerHub${NC}"
    echo "You may need to run: docker login"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Build the image
echo -e "${YELLOW}Building Docker image...${NC}"
docker build -t "${IMAGE_NAME}:latest" .

if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Docker build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Build successful${NC}"
echo ""

# Tag the image
echo -e "${YELLOW}Tagging images...${NC}"
docker tag "${IMAGE_NAME}:latest" "${DOCKER_REPO}:latest"
docker tag "${IMAGE_NAME}:latest" "${DOCKER_REPO}:${VERSION}"

echo -e "${GREEN}✓ Tagged as:${NC}"
echo -e "  - ${DOCKER_REPO}:latest"
echo -e "  - ${DOCKER_REPO}:${VERSION}"
echo ""

# Push to DockerHub
echo -e "${YELLOW}Pushing to DockerHub...${NC}"
docker push "${DOCKER_REPO}:latest"
docker push "${DOCKER_REPO}:${VERSION}"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✓ Successfully published!              ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "Image available at:"
    echo -e "  ${BLUE}https://hub.docker.com/r/${DOCKER_REPO}${NC}"
    echo ""
    echo -e "Pull with:"
    echo -e "  ${GREEN}docker pull ${DOCKER_REPO}:latest${NC}"
    echo -e "  ${GREEN}docker pull ${DOCKER_REPO}:${VERSION}${NC}"
else
    echo -e "${RED}Error: Failed to push to DockerHub${NC}"
    exit 1
fi
