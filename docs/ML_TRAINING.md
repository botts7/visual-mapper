# ML Training Server Setup

The Visual Mapper ML Training Server enables real-time Q-learning from Android exploration data. This document covers all deployment options.

## Architecture Overview

```
┌─────────────────┐         MQTT          ┌──────────────────┐
│  Android App    │ ───────────────────── │  Visual Mapper   │
│  (Exploration)  │  exploration/logs     │  Backend Server  │
│                 │ ←────────────────────│                  │
│  TFLiteQNetwork │  exploration/model    │  (Port 8080)     │
└─────────────────┘  exploration/qtable   └──────────────────┘
                                                   │
                                                   │ Optional
                                                   ▼
                                          ┌──────────────────┐
                                          │  ML Training     │
                                          │  Server          │
                                          └──────────────────┘
```

**MQTT Topics:**
- `visualmapper/exploration/logs` - Android → Server (exploration data)
- `visualmapper/exploration/qtable` - Server → Android (Q-values)
- `visualmapper/exploration/model` - Server → Android (TFLite model)
- `visualmapper/exploration/status` - Bidirectional status
- `visualmapper/exploration/command` - Commands (reset, export, train)

---

## Deployment Options

### Option 1: Built into Main Addon (Recommended)

The simplest option - ML training runs as a subprocess within the main Visual Mapper addon.

**Configuration:**

In the Home Assistant addon configuration:

```yaml
ml_training_mode: "local"    # Options: disabled, local, remote
ml_use_dqn: false            # Use Deep Q-Network (requires more resources)
ml_batch_size: 64            # Training batch size
ml_save_interval: 60         # Save model every N seconds
```

**Pros:**
- Single addon to install
- Shared data directory
- No additional network config

**Cons:**
- Increases addon memory usage when enabled
- Limited to HA host resources (no GPU/NPU on Raspberry Pi)

---

### Option 2: Remote ML Server

Run the ML training on a more powerful machine (with GPU/NPU) while the main addon handles everything else.

**Configuration:**

In the Home Assistant addon configuration:

```yaml
ml_training_mode: "remote"
ml_remote_host: "192.168.86.50"  # IP of your ML server
ml_remote_port: 8099             # Optional API port
```

**On the remote machine:**

The remote machine needs to connect to your Home Assistant's MQTT broker.

---

### Option 3: Development Machine

Best for development and testing - run ML training on your dev machine with NPU/GPU support.

#### Windows (PowerShell)

```powershell
cd scripts
.\run_ml_dev.ps1 -Broker 192.168.86.66 -Port 1883

# With authentication
.\run_ml_dev.ps1 -Broker 192.168.86.66 -Username mqtt_user -Password mqtt_pass

# Use Deep Q-Network
.\run_ml_dev.ps1 -Broker 192.168.86.66 -DQN

# Use NPU acceleration (DirectML)
.\run_ml_dev.ps1 -Broker 192.168.86.66 -DQN -UseNPU

# Use Coral Edge TPU (USB Coral accelerator)
.\run_ml_dev.ps1 -Broker 192.168.86.66 -UseCoral
```

#### Linux/Mac (Bash)

```bash
cd scripts
chmod +x run_ml_dev.sh

./run_ml_dev.sh --broker 192.168.86.66 --port 1883

# With authentication
./run_ml_dev.sh --broker 192.168.86.66 --username mqtt_user --password mqtt_pass

# Use Deep Q-Network
./run_ml_dev.sh --broker 192.168.86.66 --dqn

# Use NPU acceleration
./run_ml_dev.sh --broker 192.168.86.66 --dqn --use-npu

# Use Coral Edge TPU (USB Coral accelerator)
./run_ml_dev.sh --broker 192.168.86.66 --use-coral
```

**Command Line Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--broker`, `-b` | MQTT broker address | localhost |
| `--port`, `-p` | MQTT broker port | 1883 |
| `--username`, `-u` | MQTT username | (none) |
| `--password` | MQTT password | (none) |
| `--dqn` | Use Deep Q-Network training | false |
| `--use-npu` | Use NPU acceleration (DirectML) | false |
| `--use-coral` | Use Coral Edge TPU acceleration | false |

---

### Option 4: Docker Standalone

Run ML training as a standalone Docker container.

```bash
# Build the ML training image
docker build -f backend/Dockerfile.ml -t visual-mapper-ml:latest backend/

# Run with environment variables
docker run -d \
  --name visual-mapper-ml \
  -e MQTT_BROKER=192.168.86.66 \
  -e MQTT_PORT=1883 \
  -e USE_DQN=true \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  visual-mapper-ml:latest
```

---

## Finding Your MQTT Broker Address

### Home Assistant with Mosquitto Addon

Your MQTT broker is typically at your Home Assistant IP address on port 1883.

1. Go to **Settings** → **Add-ons** → **Mosquitto broker**
2. Note the configuration (usually uses HA's IP)
3. Default port: 1883

### Check MQTT Credentials

If you've set up MQTT authentication:

1. Go to **Settings** → **Add-ons** → **Mosquitto broker** → **Configuration**
2. Look for your username/password settings
3. Or check your `secrets.yaml` for `mqtt_username` and `mqtt_password`

---

## Hardware Accelerators

The ML Training Server supports multiple hardware accelerators for faster inference:

| Accelerator | Platform | Use Case |
|-------------|----------|----------|
| **Coral Edge TPU** | USB/M.2/PCIe | Raspberry Pi, Linux servers |
| **DirectML (NPU)** | Windows ARM/x64 | Windows laptops with NPU |
| **CUDA (GPU)** | NVIDIA GPUs | High-performance servers |
| **CPU** | All platforms | Fallback, always available |

### Coral Edge TPU Setup

Google Coral Edge TPU provides fast, low-power inference acceleration. Works great on Raspberry Pi with USB Coral.

**1. Install libedgetpu (Linux/Raspberry Pi):**

```bash
# Add Coral repository
echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt update

# Install runtime (choose one):
sudo apt install libedgetpu1-std    # Standard performance
# OR
sudo apt install libedgetpu1-max    # Max performance (higher power)
```

**2. Install pycoral:**

```bash
pip install pycoral
```

**3. Connect USB Coral and verify:**

```bash
# Check USB device detected
lsusb | grep Google
# Should show: Google Inc. Coral USB Accelerator

# Test detection
python -c "from pycoral.utils.edgetpu import list_edge_tpus; print(list_edge_tpus())"
```

**4. Run ML Training with Coral:**

```bash
./run_ml_dev.sh --broker 192.168.86.66 --use-coral
```

**Note:** Coral Edge TPU only supports inference, not training. The ML server trains on CPU and uses Coral for fast inference during exploration.

### DirectML (Windows NPU)

For Windows devices with NPU (Neural Processing Unit) support:

```powershell
# Install onnxruntime with DirectML
pip install onnxruntime-directml

# Run with DirectML acceleration
.\run_ml_dev.ps1 -Broker 192.168.86.66 -UseNPU
```

### CUDA (NVIDIA GPU)

For NVIDIA GPUs:

```bash
# Install PyTorch with CUDA support
pip install torch --index-url https://download.pytorch.org/whl/cu118

# Run with DQN (automatically uses CUDA if available)
./run_ml_dev.sh --broker 192.168.86.66 --dqn
```

---

## Training Modes

### Q-Table Learning (Default)

Simple, efficient learning that works well on low-power devices:
- Stores state-action values in a table
- Fast updates, low memory usage
- Good for simple navigation patterns

### Deep Q-Network (DQN)

Neural network-based learning for complex scenarios:
- Better generalization across similar states
- Handles larger state spaces
- Requires more computational resources
- Benefits from GPU/NPU acceleration

**When to use DQN:**
- Complex apps with many screens
- When Q-table becomes too large
- When you have GPU/NPU available

---

## Verifying ML Training is Working

### 1. Check Addon Logs

In Home Assistant:
```
Settings → Add-ons → Visual Mapper → Logs
```

Look for:
```
[MLTrainingServer] Starting ML Training Server...
[MLTrainingServer] Connected to MQTT broker
[MLTrainingServer] Subscribed to exploration/logs
```

### 2. Check MQTT Messages

Use MQTT Explorer or similar tool to monitor:
- `visualmapper/exploration/logs` - Should see exploration data from Android
- `visualmapper/exploration/qtable` - Should see Q-value updates
- `visualmapper/exploration/status` - Should see status messages

### 3. Check Android App

In the Visual Mapper Android app:
1. Go to **Settings** → **ML Training**
2. Should show "Connected" status
3. Q-values should update during exploration

---

## Troubleshooting

### "Connection refused" to MQTT

1. Verify MQTT broker address is correct
2. Check if Mosquitto addon is running
3. Verify firewall allows port 1883
4. Try using IP address instead of hostname

### "Authentication failed"

1. Verify username/password are correct
2. Check Mosquitto addon configuration
3. Ensure user has publish/subscribe permissions

### ML Server not receiving exploration data

1. Check Android app is connected to same MQTT broker
2. Verify topic names match (`visualmapper/exploration/logs`)
3. Check Android app has ML training enabled in settings

### High memory usage

1. Try Q-table mode instead of DQN
2. Reduce `ml_batch_size` in configuration
3. Consider running ML on a separate machine

---

## Environment Variables

For advanced configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `ML_TRAINING` | Enable ML training | false |
| `ML_ENABLED` | Enable ML components | false |
| `MQTT_BROKER` | MQTT broker address | localhost |
| `MQTT_PORT` | MQTT broker port | 1883 |
| `ML_DATA_DIR` | Directory for ML data/models | ./data |

---

## Resource Requirements

### Minimum (Q-Table, local mode)
- RAM: 512MB additional
- CPU: Any
- Storage: 50MB for Q-table

### Recommended (DQN, local mode)
- RAM: 2GB additional
- CPU: Multi-core
- Storage: 200MB for models

### Optimal (DQN with acceleration)
- RAM: 4GB+
- GPU/NPU: CUDA, DirectML, or Metal
- Storage: 500MB for models and checkpoints

### With Coral Edge TPU
- RAM: 1GB additional
- USB: Coral USB Accelerator connected
- Storage: 100MB for quantized models
- Inference: ~10-50x faster than CPU
