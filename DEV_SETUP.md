# Visual Mapper - Development Environment Setup

**Version:** 0.0.1
**Created:** 2025-12-22

---

## Quick Start

### Start Everything

```bash
# Start all services (Visual Mapper + Home Assistant + MQTT)
docker-compose -f docker-compose.dev.yml up -d

# View logs
docker-compose -f docker-compose.dev.yml logs -f
```

### Access Services

- **Visual Mapper Frontend:** http://localhost:8099/
- **Visual Mapper API:** http://localhost:8099/api/health
- **Home Assistant:** http://localhost:8123
- **MQTT Broker:** localhost:1883

### Stop Everything

```bash
docker-compose -f docker-compose.dev.yml down
```

---

## Services

### 1. Visual Mapper (visual-mapper)
- **Port:** 8099
- **Purpose:** Main addon development
- **Hot Reload:** Yes (www/, server.py, adb_bridge.py)
- **Health Check:** http://localhost:8099/api/health

### 2. Home Assistant (homeassistant)
- **Port:** 8123
- **Purpose:** Test addon in real HA environment
- **Config:** ./ha-config/
- **First Login:** Create account on first access

### 3. Mosquitto MQTT (mosquitto)
- **Ports:** 1883 (MQTT), 9001 (WebSocket)
- **Purpose:** Test sensor publishing (Phase 3+)
- **Config:** ./mosquitto/config/mosquitto.conf

---

## First Time Setup

### 1. Build and Start

```bash
docker-compose -f docker-compose.dev.yml up --build
```

### 2. Access Home Assistant

1. Open http://localhost:8123
2. Create admin account
3. Complete onboarding wizard
4. Skip integrations for now

### 3. Configure Visual Mapper in HA

Home Assistant will eventually load Visual Mapper as an addon. For now, we're testing the standalone service.

### 4. Test Visual Mapper

```bash
# Check backend health
curl http://localhost:8099/api/health

# Open frontend
open http://localhost:8099/
```

---

## Development Workflow

### Code Changes

1. Edit files in `www/`, `server.py`, or `adb_bridge.py`
2. Changes auto-reload (volumes mounted)
3. Refresh browser to see changes
4. Check logs: `docker-compose -f docker-compose.dev.yml logs -f visual-mapper`

### Running Tests

```bash
# Python unit tests
docker-compose -f docker-compose.dev.yml exec visual-mapper pytest

# Or run locally
pytest
```

### Debugging

```bash
# View Visual Mapper logs
docker-compose -f docker-compose.dev.yml logs -f visual-mapper

# View Home Assistant logs
docker-compose -f docker-compose.dev.yml logs -f homeassistant

# View MQTT logs
docker-compose -f docker-compose.dev.yml logs -f mosquitto

# Shell into container
docker-compose -f docker-compose.dev.yml exec visual-mapper sh
```

---

## Troubleshooting

### Port Already in Use

```bash
# Stop all containers
docker-compose -f docker-compose.dev.yml down

# Check what's using the port
netstat -ano | findstr :8099
netstat -ano | findstr :8123

# Kill process or change ports in docker-compose.dev.yml
```

### Home Assistant Not Starting

```bash
# Check logs
docker-compose -f docker-compose.dev.yml logs homeassistant

# Remove and recreate
docker-compose -f docker-compose.dev.yml down
rm -rf ha-config/.storage
docker-compose -f docker-compose.dev.yml up homeassistant
```

### Visual Mapper Not Loading

```bash
# Rebuild container
docker-compose -f docker-compose.dev.yml up --build visual-mapper

# Check health
curl http://localhost:8099/api/health
```

---

## Cleanup

### Remove Containers

```bash
docker-compose -f docker-compose.dev.yml down
```

### Remove Volumes (Full Reset)

```bash
docker-compose -f docker-compose.dev.yml down -v
rm -rf ha-config/.storage
rm -rf mosquitto/data/*
rm -rf mosquitto/log/*
```

---

## Next Steps

1. **Phase 0 (Current):** Basic infrastructure ✅
2. **Phase 1:** Add ADB connection and screenshot capture
3. **Phase 3:** Test MQTT sensor publishing to Home Assistant
4. **Phase 4:** Test live streaming

---

**Related Files:**
- [docker-compose.dev.yml](docker-compose.dev.yml)
- [ha-config/configuration.yaml](ha-config/configuration.yaml)
- [mosquitto/config/mosquitto.conf](mosquitto/config/mosquitto.conf)
- [40_LOCAL_DEV_ENVIRONMENT.md](40_LOCAL_DEV_ENVIRONMENT.md)
