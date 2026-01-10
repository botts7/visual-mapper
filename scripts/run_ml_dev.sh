#!/bin/bash
# Visual Mapper ML Training Server - Linux/Mac Development Script
# Run this on your dev machine with GPU/NPU to train ML models
#
# Usage:
#   ./run_ml_dev.sh                          # Uses localhost MQTT
#   ./run_ml_dev.sh --broker 192.168.86.66   # Connect to HA MQTT
#   ./run_ml_dev.sh --broker 192.168.86.66 --dqn  # Use Deep Q-Network

set -e

# Default values
BROKER="localhost"
PORT=1883
USERNAME=""
PASSWORD=""
DQN=""
USE_NPU=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --broker|-b)
            BROKER="$2"
            shift 2
            ;;
        --port|-p)
            PORT="$2"
            shift 2
            ;;
        --username|-u)
            USERNAME="$2"
            shift 2
            ;;
        --password)
            PASSWORD="$2"
            shift 2
            ;;
        --dqn)
            DQN="--dqn"
            shift
            ;;
        --use-npu|--npu)
            USE_NPU="--use-npu"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --broker, -b    MQTT broker address (default: localhost)"
            echo "  --port, -p      MQTT broker port (default: 1883)"
            echo "  --username, -u  MQTT username"
            echo "  --password      MQTT password"
            echo "  --dqn           Use Deep Q-Network training"
            echo "  --use-npu       Use NPU acceleration (DirectML)"
            echo "  -h, --help      Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Find script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")/backend"

if [ ! -d "$BACKEND_DIR" ]; then
    echo "Error: Backend directory not found: $BACKEND_DIR"
    exit 1
fi

echo "========================================"
echo " Visual Mapper ML Training Server"
echo "========================================"
echo ""
echo "MQTT Broker: $BROKER:$PORT"
if [ -n "$DQN" ]; then
    echo "Mode: Deep Q-Network (DQN)"
else
    echo "Mode: Q-Table Learning"
fi
if [ -n "$USE_NPU" ]; then
    echo "Acceleration: NPU (DirectML)"
fi
echo ""

# Build command
CMD="python ml_components/ml_training_server.py --broker $BROKER --port $PORT"

if [ -n "$USERNAME" ]; then
    CMD="$CMD --username $USERNAME"
fi
if [ -n "$PASSWORD" ]; then
    CMD="$CMD --password $PASSWORD"
fi
if [ -n "$DQN" ]; then
    CMD="$CMD $DQN"
fi
if [ -n "$USE_NPU" ]; then
    CMD="$CMD $USE_NPU"
fi

# Set environment and run
export PYTHONPATH="$BACKEND_DIR"
export ML_TRAINING="true"

cd "$BACKEND_DIR"

echo "Starting ML Training Server..."
echo "Press Ctrl+C to stop"
echo ""

$CMD
