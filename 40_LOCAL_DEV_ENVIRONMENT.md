# Local Development Environment

**Purpose:** Setup local development environment for Visual Mapper.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## 🎯 Overview

**Three development options:**
1. Docker Compose (recommended)
2. VS Code Devcontainer (HA official method)
3. Local Python + nginx

---

## 🐳 Option 1: Docker Compose (Recommended)

### **docker-compose.dev.yml**

```yaml
version: '3.8'

services:
  visual-mapper-dev:
    build:
      context: .
      dockerfile: Dockerfile.dev
    ports:
      - "3000:3000"   # Frontend
      - "8099:8099"   # Backend API
      - "8100:8100"   # Stream server
    volumes:
      - ./www:/app/www:ro
      - ./server.py:/app/server.py:ro
      - ./adb_bridge.py:/app/adb_bridge.py:ro
    environment:
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=debug
    command: uvicorn server:app --host 0.0.0.0 --port 8099 --reload

  # Optional: Mock Home Assistant for testing
  homeassistant:
    image: homeassistant/home-assistant:latest
    ports:
      - "8123:8123"
    volumes:
      - ./ha-config:/config

  # Optional: MQTT broker for sensor testing
  mosquitto:
    image: eclipse-mosquitto:latest
    ports:
      - "1883:1883"
```

### **Usage**

```bash
# Start all services
docker-compose -f docker-compose.dev.yml up

# Start specific service
docker-compose -f docker-compose.dev.yml up visual-mapper-dev

# Rebuild after code changes
docker-compose -f docker-compose.dev.yml up --build

# View logs
docker-compose -f docker-compose.dev.yml logs -f visual-mapper-dev
```

---

## 💻 Option 2: VS Code Devcontainer

### **.devcontainer/devcontainer.json**

```json
{
  "name": "Visual Mapper Development",
  "dockerComposeFile": "../docker-compose.dev.yml",
  "service": "visual-mapper-dev",
  "workspaceFolder": "/app",

  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance",
        "dbaeumer.vscode-eslint",
        "esbenp.prettier-vscode",
        "ms-playwright.playwright"
      ],
      "settings": {
        "python.defaultInterpreterPath": "/usr/local/bin/python",
        "python.linting.enabled": true,
        "python.linting.pylintEnabled": true,
        "editor.formatOnSave": true
      }
    }
  },

  "forwardPorts": [3000, 8099, 8100],

  "postCreateCommand": "pip install -r requirements.txt && npm install",

  "remoteUser": "vscode"
}
```

### **Usage**

1. Install "Remote - Containers" extension in VS Code
2. Open project folder
3. Click "Reopen in Container"
4. Wait for container build
5. Start coding!

---

## 🔧 Option 3: Local Development

### **Requirements**

- Python 3.11+
- Node.js 18+ (for testing)
- nginx (for reverse proxy)

### **Setup**

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install JS dependencies
npm install

# Start backend
uvicorn server:app --reload --port 8099

# Start nginx (separate terminal)
nginx -c $(pwd)/nginx.conf

# Open browser
http://localhost:3000
```

---

## 📁 Project Structure

```
visual_mapper_v3_copy/
├── docker-compose.dev.yml
├── Dockerfile.dev
├── .devcontainer/
│   └── devcontainer.json
├── www/                    # Hot reload
├── server.py               # Hot reload
├── adb_bridge.py           # Hot reload
├── tests/
└── docs/
```

---

## 🧪 Testing in Dev Environment

```bash
# Run all tests
npm test

# Run specific test
playwright test tests/e2e/navigation.spec.js

# Run with browser visible
playwright test --headed

# Python tests
pytest
```

---

## 📚 Related Documentation

- [41_TESTING_PLAYWRIGHT.md](41_TESTING_PLAYWRIGHT.md) - E2E testing
- [42_TESTING_JEST_PYTEST.md](42_TESTING_JEST_PYTEST.md) - Unit testing

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 0.0.1+
