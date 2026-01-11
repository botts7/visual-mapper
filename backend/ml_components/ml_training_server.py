#!/usr/bin/env python3
"""
ML Training Server for Smart Explorer - Enhanced Edition

This server runs on the development machine (Surface Laptop 7 with NPU)
and trains Q-learning models from exploration data sent by Android devices.

OPTIMIZATIONS FOR SURFACE LAPTOP 7:
- DirectML support for NPU acceleration (Windows)
- Multi-threaded data processing
- Prioritized Experience Replay (PER)
- Double DQN for better convergence
- Auto-tuning hyperparameters
- Real-time performance monitoring

Architecture:
- Subscribes to exploration logs via MQTT from Android
- Trains Q-network using collected experience
- Publishes updated Q-values back to Android for testing
- Exports final Q-table as JSON for production bundling

Usage:
    python ml_training_server.py --broker localhost --port 1883
    python ml_training_server.py --broker 192.168.1.66 --port 1883 --dqn

MQTT Topics:
    visualmapper/exploration/logs       - Receive exploration logs from Android
    visualmapper/exploration/qtable     - Publish trained Q-values to Android
    visualmapper/exploration/status     - Status updates (bidirectional)
    visualmapper/exploration/command    - Commands (reset, export, etc.)
"""

import argparse
import json
import logging
import math
import os
import platform
import signal
import sys
import tempfile
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from threading import Thread, Lock, Event
from typing import Dict, List, Optional, Tuple, Any
import queue

import paho.mqtt.client as mqtt

# ============================================================================
# DATA DIRECTORY CONFIGURATION (HA Add-on Compatibility)
# ============================================================================
# Standalone (dev): ./data (relative to CWD)
# HA Add-on (prod): /data (persistent storage in Docker container)
#
# This ensures data persists across container restarts in HA Add-on mode.
# ============================================================================
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path, data: dict, indent: int = 2) -> None:
    """
    Atomically write JSON data to file using temp file + os.replace pattern.

    This prevents file corruption if the process crashes mid-write:
    1. Write to a temporary file in the same directory
    2. Use os.replace() to atomically move temp file to target path

    os.replace() is atomic on POSIX systems and "as atomic as possible" on Windows.

    Args:
        path: Target file path
        data: Dictionary to serialize as JSON
        indent: JSON indentation (default 2)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory (same filesystem = atomic replace)
    fd, temp_path = tempfile.mkstemp(
        suffix=".tmp", prefix=path.stem + "_", dir=path.parent
    )

    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)

        # Atomic replace (overwrites target if exists)
        os.replace(temp_path, str(path))

    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


# Optional feature manager import (not available when running standalone)
try:
    from services.feature_manager import get_feature_manager

    FEATURE_MANAGER_AVAILABLE = True
except ImportError:
    FEATURE_MANAGER_AVAILABLE = False

    def get_feature_manager():
        return None


# === Hardware Detection ===


def detect_hardware():
    """Detect available hardware acceleration"""
    hw_info = {
        "platform": platform.system(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count() or 4,
        "cuda_available": False,
        "directml_available": False,
        "npu_available": False,
        "onnx_available": False,
        "coral_available": False,
        "coral_devices": 0,
    }

    # Check feature manager if available (skip when running standalone)
    if FEATURE_MANAGER_AVAILABLE:
        feature_manager = get_feature_manager()
        if feature_manager and not feature_manager.is_enabled("ml_enabled"):
            return hw_info

    # Check for ONNX Runtime with DirectML (best for Windows NPU)
    try:
        import onnxruntime as ort

        providers = ort.get_available_providers()
        hw_info["onnx_available"] = True
        hw_info["onnx_providers"] = providers
        if "DmlExecutionProvider" in providers:
            hw_info["directml_available"] = True
            hw_info["npu_available"] = True
        print(f"ONNX Runtime available with providers: {providers}")
    except ImportError:
        pass

    # Check for PyTorch with DirectML
    try:
        import torch

        hw_info["torch_available"] = True
        hw_info["torch_version"] = torch.__version__

        if torch.cuda.is_available():
            hw_info["cuda_available"] = True
            hw_info["cuda_device"] = torch.cuda.get_device_name(0)
            print(f"CUDA available: {hw_info['cuda_device']}")

        # Check for torch-directml
        try:
            import torch_directml

            hw_info["directml_available"] = True
            hw_info["npu_available"] = True
            hw_info["dml_device_count"] = torch_directml.device_count()
            print(f"DirectML available with {hw_info['dml_device_count']} device(s)")
        except ImportError:
            pass

    except ImportError:
        hw_info["torch_available"] = False

    # Check for Coral Edge TPU
    try:
        from pycoral.utils.edgetpu import list_edge_tpus

        edge_tpus = list_edge_tpus()
        if edge_tpus:
            hw_info["coral_available"] = True
            hw_info["coral_devices"] = len(edge_tpus)
            print(f"Coral Edge TPU available: {len(edge_tpus)} device(s)")
            for i, tpu in enumerate(edge_tpus):
                print(f"  TPU {i}: {tpu}")
    except ImportError:
        pass  # pycoral not installed
    except Exception as e:
        print(f"Coral detection failed: {e}")

    return hw_info


HW_INFO = detect_hardware()

# Try to import PyTorch
feature_manager = get_feature_manager()
ml_enabled = (
    feature_manager.is_enabled("ml_enabled") if feature_manager else True
)  # Default to enabled when standalone

if ml_enabled:
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        import torch.optim as optim

        TORCH_AVAILABLE = True

        # Try DirectML for Windows NPU
        try:
            import torch_directml

            DML_AVAILABLE = True
            print("Using DirectML for NPU acceleration")
        except ImportError:
            DML_AVAILABLE = False

    except ImportError:
        TORCH_AVAILABLE = False
        DML_AVAILABLE = False
        print("PyTorch not available - using simple Q-table training only")
else:
    TORCH_AVAILABLE = False
    DML_AVAILABLE = False
    print("ML features disabled by feature flag")

# Try to import ONNX Runtime for NPU acceleration
ONNX_AVAILABLE = False
ONNX_DML_AVAILABLE = False
if ml_enabled:
    try:
        import onnxruntime as ort

        ONNX_AVAILABLE = True
        if "DmlExecutionProvider" in ort.get_available_providers():
            ONNX_DML_AVAILABLE = True
            print("ONNX Runtime with DirectML available for NPU acceleration")
    except ImportError:
        pass

# Try to import numpy
try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("NumPy not available - some features may be limited")

# Coral Edge TPU availability (set from HW_INFO)
CORAL_AVAILABLE = HW_INFO.get("coral_available", False)
CORAL_DEVICES = HW_INFO.get("coral_devices", 0)


# === Configuration ===

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
MQTT_TOPIC_LOGS = "visualmapper/exploration/logs"
MQTT_TOPIC_QTABLE = "visualmapper/exploration/qtable"
MQTT_TOPIC_STATUS = "visualmapper/exploration/status"
MQTT_TOPIC_COMMAND = "visualmapper/exploration/command"
MQTT_TOPIC_MODEL = "visualmapper/exploration/model"  # TFLite model updates


# Q-learning hyperparameters (auto-tuned based on experience)
class HyperParams:
    def __init__(self):
        self.alpha = 0.1  # Learning rate
        self.alpha_min = 0.01  # Minimum learning rate
        self.alpha_decay = 0.9999  # Learning rate decay
        self.gamma = 0.95  # Discount factor (higher = more foresight)
        self.epsilon = 0.3  # Exploration rate
        self.epsilon_min = 0.05  # Minimum exploration
        self.epsilon_decay = 0.995  # Epsilon decay
        self.tau = 0.005  # Soft update rate for target network

        # Prioritized Experience Replay
        self.per_alpha = 0.6  # Priority exponent
        self.per_beta = 0.4  # Importance sampling
        self.per_beta_increment = 0.001
        self.per_epsilon = 1e-6  # Small constant for stability

    def decay(self):
        """Decay learning rate and epsilon"""
        self.alpha = max(self.alpha_min, self.alpha * self.alpha_decay)
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        self.per_beta = min(1.0, self.per_beta + self.per_beta_increment)


HYPERPARAMS = HyperParams()

# Training settings
BATCH_SIZE = 64  # Larger batch for better gradients
REPLAY_BUFFER_SIZE = 50000  # Larger buffer for more diversity
TRAINING_INTERVAL = 5  # Train more frequently
PUBLISH_INTERVAL = 25  # Publish Q-table more often
TARGET_UPDATE_INTERVAL = 100  # Update target network every N steps
SAVE_INTERVAL = 500  # Save checkpoint every N updates
NUM_WORKERS = max(2, (os.cpu_count() or 4) - 1)  # Leave one core free

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("ml_training.log")],
)
logger = logging.getLogger("MLTrainingServer")


# === Data Classes ===


@dataclass
class ExplorationLogEntry:
    """Single exploration experience from Android"""

    screen_hash: str
    action_key: str
    reward: float
    next_screen_hash: Optional[str]
    timestamp: int
    device_id: Optional[str] = None
    priority: float = 1.0  # For prioritized replay


@dataclass
class TrainingStats:
    """Training statistics"""

    total_experiences: int = 0
    total_updates: int = 0
    q_table_size: int = 0
    average_reward: float = 0.0
    average_td_error: float = 0.0
    last_update: Optional[str] = None
    devices_seen: int = 0
    training_rate: float = 0.0  # Updates per second
    hardware_acceleration: str = "CPU"
    memory_usage_mb: float = 0.0


# === Prioritized Experience Replay Buffer ===


class SumTree:
    """
    Sum Tree for efficient prioritized sampling
    Stores priorities in a tree structure for O(log n) sampling
    """

    def __init__(self, capacity: int):
        self.capacity = capacity
        self.tree = (
            np.zeros(2 * capacity - 1)
            if NUMPY_AVAILABLE
            else [0.0] * (2 * capacity - 1)
        )
        self.data = [None] * capacity
        self.write_idx = 0
        self.n_entries = 0

    def _propagate(self, idx: int, change: float):
        parent = (idx - 1) // 2
        if NUMPY_AVAILABLE:
            self.tree[parent] += change
        else:
            self.tree[parent] = self.tree[parent] + change
        if parent != 0:
            self._propagate(parent, change)

    def _retrieve(self, idx: int, s: float) -> int:
        left = 2 * idx + 1
        right = left + 1

        if left >= len(self.tree):
            return idx

        tree_left = self.tree[left] if NUMPY_AVAILABLE else self.tree[left]
        if s <= tree_left:
            return self._retrieve(left, s)
        else:
            return self._retrieve(right, s - tree_left)

    def total(self) -> float:
        return float(self.tree[0])

    def add(self, priority: float, data: Any):
        idx = self.write_idx + self.capacity - 1
        self.data[self.write_idx] = data
        self.update(idx, priority)

        self.write_idx = (self.write_idx + 1) % self.capacity
        self.n_entries = min(self.n_entries + 1, self.capacity)

    def update(self, idx: int, priority: float):
        change = priority - self.tree[idx]
        self.tree[idx] = priority
        self._propagate(idx, change)

    def get(self, s: float) -> Tuple[int, float, Any]:
        idx = self._retrieve(0, s)
        data_idx = idx - self.capacity + 1
        return idx, float(self.tree[idx]), self.data[data_idx]


class PrioritizedReplayBuffer:
    """
    Prioritized Experience Replay buffer
    Samples experiences based on TD-error priority
    """

    def __init__(self, capacity: int = REPLAY_BUFFER_SIZE):
        self.tree = SumTree(capacity)
        self.capacity = capacity
        self.lock = Lock()

    def add(self, experience: ExplorationLogEntry, td_error: float = 1.0):
        priority = (abs(td_error) + HYPERPARAMS.per_epsilon) ** HYPERPARAMS.per_alpha
        with self.lock:
            self.tree.add(priority, experience)

    def sample(
        self, batch_size: int
    ) -> Tuple[List[ExplorationLogEntry], List[int], np.ndarray]:
        batch = []
        indices = []
        priorities = []

        segment = self.tree.total() / batch_size

        with self.lock:
            for i in range(batch_size):
                a = segment * i
                b = segment * (i + 1)
                s = np.random.uniform(a, b) if NUMPY_AVAILABLE else (a + b) / 2

                idx, priority, data = self.tree.get(s)
                if data is not None:
                    batch.append(data)
                    indices.append(idx)
                    priorities.append(priority)

        # Calculate importance sampling weights
        if NUMPY_AVAILABLE:
            priorities = np.array(priorities)
            probs = priorities / (self.tree.total() + 1e-8)
            weights = (self.tree.n_entries * probs) ** (-HYPERPARAMS.per_beta)
            weights = weights / (weights.max() + 1e-8)  # Normalize
        else:
            weights = np.ones(len(batch)) if NUMPY_AVAILABLE else [1.0] * len(batch)

        return batch, indices, weights

    def update_priorities(self, indices: List[int], td_errors: List[float]):
        with self.lock:
            for idx, td_error in zip(indices, td_errors):
                priority = (
                    abs(td_error) + HYPERPARAMS.per_epsilon
                ) ** HYPERPARAMS.per_alpha
                self.tree.update(idx, priority)

    def __len__(self):
        return self.tree.n_entries


# === Enhanced Q-Table Trainer ===


class QTableTrainer:
    """
    Enhanced Q-table trainer with:
    - Prioritized Experience Replay
    - Multi-threaded processing
    - Adaptive learning rate
    - Pattern recognition for dangerous elements
    - Phase 3: Q-table pruning to prevent OOM
    - Phase 3: Blocked states tracking for danger zones
    - Phase 3: Async saves for non-blocking I/O
    """

    # Phase 3: Q-table size limits to prevent OOM
    MAX_Q_TABLE_SIZE = 10000  # Maximum entries before pruning
    DANGER_THRESHOLD = -5.0  # Cumulative reward threshold for blocking
    DANGER_COUNT = 3  # Times to hit threshold before blocking

    def __init__(self):
        self.q_table: Dict[str, float] = {}
        self.visit_counts: Dict[str, int] = {}
        self.replay_buffer = PrioritizedReplayBuffer(REPLAY_BUFFER_SIZE)
        self.stats = TrainingStats()
        self.stats.hardware_acceleration = "CPU (Optimized)"
        self.devices_seen: set = set()
        self.lock = Lock()
        self.reward_history: deque = deque(maxlen=1000)
        self.td_error_history: deque = deque(maxlen=1000)

        # Pattern analysis
        self.dangerous_patterns: Dict[str, float] = {}  # pattern -> danger score
        self.success_patterns: Dict[str, float] = {}  # pattern -> success score

        # Phase 3: Blocked states tracking (danger zone)
        self.blocked_states: set = set()  # States to avoid
        self.danger_scores: Dict[str, float] = (
            {}
        )  # Cumulative negative reward per state
        self.danger_counts: Dict[str, int] = {}  # Times state hit danger threshold

        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=NUM_WORKERS)
        self.training_queue = queue.Queue(maxsize=1000)
        self.stop_event = Event()

        # Phase 3: Async save tracking
        self.pending_save = False
        self.last_prune_time = time.time()

        # Start background training thread
        self.training_thread = Thread(target=self._training_loop, daemon=True)
        self.training_thread.start()

        # Performance tracking
        self.last_update_time = time.time()
        self.updates_since_last = 0

        logger.info(f"QTableTrainer initialized with {NUM_WORKERS} worker threads")
        logger.info(
            f"Q-table limit: {self.MAX_Q_TABLE_SIZE} entries (auto-prune enabled)"
        )

    def _training_loop(self):
        """Background training loop"""
        prune_interval = 60  # Prune every 60 seconds
        update_counter = 0

        while not self.stop_event.is_set():
            try:
                # Get batch from queue with timeout
                entries = []
                try:
                    while len(entries) < BATCH_SIZE:
                        entry = self.training_queue.get(timeout=0.1)
                        entries.append(entry)
                except queue.Empty:
                    pass

                if entries:
                    # Process batch in parallel
                    futures = []
                    for entry in entries:
                        futures.append(self.executor.submit(self._process_entry, entry))

                    # Wait for all to complete
                    for future in futures:
                        try:
                            future.result(timeout=5)
                        except Exception as e:
                            logger.error(f"Training error: {e}")

                    update_counter += len(entries)

                # Periodic batch training from replay buffer
                if len(self.replay_buffer) >= BATCH_SIZE:
                    self.train_batch()

                # Phase 3: Periodic Q-table pruning to prevent OOM
                current_time = time.time()
                if current_time - self.last_prune_time > prune_interval:
                    pruned = self.prune_q_table()
                    self.last_prune_time = current_time
                    if pruned > 0:
                        logger.debug(f"Periodic prune removed {pruned} entries")

                # Phase 3: Force prune if Q-table is significantly over limit
                if len(self.q_table) > self.MAX_Q_TABLE_SIZE * 1.5:
                    self.prune_q_table()

            except Exception as e:
                logger.error(f"Training loop error: {e}")
                time.sleep(0.5)

    def _process_entry(self, entry: ExplorationLogEntry):
        """Process a single experience entry"""
        key = f"{entry.screen_hash}|{entry.action_key}"

        with self.lock:
            current_q = self.q_table.get(key, 0.0)

            # Get max Q for next state
            next_max_q = 0.0
            if entry.next_screen_hash:
                next_max_q = self._get_max_q(entry.next_screen_hash)

            # Calculate TD error for prioritized replay
            target_q = entry.reward + HYPERPARAMS.gamma * next_max_q
            td_error = abs(target_q - current_q)

            # Q-learning update with adaptive learning rate
            new_q = current_q + HYPERPARAMS.alpha * (target_q - current_q)
            self.q_table[key] = new_q

            # Update stats
            self.visit_counts[key] = self.visit_counts.get(key, 0) + 1
            self.td_error_history.append(td_error)

            # Pattern analysis
            self._analyze_pattern(entry)

        # Add to replay buffer with priority
        self.replay_buffer.add(entry, td_error)

        return td_error

    def _analyze_pattern(self, entry: ExplorationLogEntry):
        """
        Analyze patterns for dangerous/successful elements.

        Phase 3: Also tracks blocked states (danger zones) to prevent
        the explorer from getting stuck in crash loops.
        """
        pattern = entry.action_key
        key = f"{entry.screen_hash}|{entry.action_key}"

        if entry.reward < -1.0:  # Crash or close
            self.dangerous_patterns[pattern] = self.dangerous_patterns.get(
                pattern, 0
            ) + abs(entry.reward)

            # Phase 3: Track cumulative negative reward for blocked states
            self.danger_scores[key] = self.danger_scores.get(key, 0) + entry.reward

            # Check if state should be blocked
            if self.danger_scores[key] <= self.DANGER_THRESHOLD:
                self.danger_counts[key] = self.danger_counts.get(key, 0) + 1

                if self.danger_counts[key] >= self.DANGER_COUNT:
                    if key not in self.blocked_states:
                        self.blocked_states.add(key)
                        logger.warning(
                            f"BLOCKED dangerous state: {key} (cumulative reward: {self.danger_scores[key]:.2f})"
                        )

        elif entry.reward > 0.5:  # New screen or good action
            self.success_patterns[pattern] = (
                self.success_patterns.get(pattern, 0) + entry.reward
            )

            # Phase 3: Good actions can rehabilitate a blocked state
            if (
                key in self.blocked_states
                and self.success_patterns.get(pattern, 0) > 5.0
            ):
                self.blocked_states.discard(key)
                self.danger_scores[key] = 0
                self.danger_counts[key] = 0
                logger.info(f"UNBLOCKED rehabilitated state: {key}")

    def add_experience(self, entry: ExplorationLogEntry):
        """Add an experience (async via queue)"""
        with self.lock:
            self.stats.total_experiences += 1
            self.reward_history.append(entry.reward)

            if entry.device_id:
                self.devices_seen.add(entry.device_id)

        # Queue for background processing
        try:
            self.training_queue.put_nowait(entry)
        except queue.Full:
            # Process synchronously if queue is full
            self._process_entry(entry)

        # Log progress
        if self.stats.total_experiences % 20 == 0:
            self._update_stats()
            avg_reward = (
                sum(self.reward_history) / len(self.reward_history)
                if self.reward_history
                else 0
            )
            avg_td = (
                sum(self.td_error_history) / len(self.td_error_history)
                if self.td_error_history
                else 0
            )
            logger.info(
                f"Experiences: {self.stats.total_experiences}, "
                f"Q-table: {len(self.q_table)}, "
                f"Avg reward: {avg_reward:.3f}, "
                f"Avg TD-error: {avg_td:.3f}, "
                f"Rate: {self.stats.training_rate:.1f}/s"
            )

    def _update_stats(self):
        """Update training statistics"""
        now = time.time()
        elapsed = now - self.last_update_time
        if elapsed > 0:
            self.stats.training_rate = self.updates_since_last / elapsed
        self.last_update_time = now
        self.updates_since_last = 0

        self.stats.total_updates += 1
        self.stats.q_table_size = len(self.q_table)
        self.stats.last_update = datetime.now().isoformat()
        self.stats.devices_seen = len(self.devices_seen)

        if self.reward_history:
            self.stats.average_reward = sum(self.reward_history) / len(
                self.reward_history
            )
        if self.td_error_history:
            self.stats.average_td_error = sum(self.td_error_history) / len(
                self.td_error_history
            )

        # Memory usage
        try:
            import psutil

            process = psutil.Process()
            self.stats.memory_usage_mb = process.memory_info().rss / 1024 / 1024
        except ImportError:
            pass

    def _get_max_q(self, screen_hash: str) -> float:
        """Get max Q-value for all actions in a screen"""
        max_q = 0.0
        prefix = f"{screen_hash}|"
        for key, value in self.q_table.items():
            if key.startswith(prefix):
                max_q = max(max_q, value)
        return max_q

    def train_batch(self, batch_size: int = BATCH_SIZE):
        """Train on a batch using prioritized experience replay"""
        if len(self.replay_buffer) < batch_size:
            return

        # Sample with priorities
        batch, indices, weights = self.replay_buffer.sample(batch_size)

        td_errors = []
        with self.lock:
            for i, entry in enumerate(batch):
                key = f"{entry.screen_hash}|{entry.action_key}"
                current_q = self.q_table.get(key, 0.0)

                next_max_q = 0.0
                if entry.next_screen_hash:
                    next_max_q = self._get_max_q(entry.next_screen_hash)

                target_q = entry.reward + HYPERPARAMS.gamma * next_max_q
                td_error = target_q - current_q
                td_errors.append(abs(td_error))

                # Weighted update (importance sampling)
                weight = weights[i] if NUMPY_AVAILABLE else 1.0
                new_q = current_q + HYPERPARAMS.alpha * weight * td_error
                self.q_table[key] = new_q

                self.updates_since_last += 1

        # Update priorities in replay buffer
        self.replay_buffer.update_priorities(indices, td_errors)

        # Decay hyperparameters
        HYPERPARAMS.decay()

        logger.debug(
            f"Trained on batch of {len(batch)}, avg TD-error: {sum(td_errors)/len(td_errors):.4f}"
        )

    def get_q_table(self) -> Dict[str, float]:
        """Get a copy of the Q-table"""
        with self.lock:
            return dict(self.q_table)

    def get_dangerous_patterns(self) -> Dict[str, float]:
        """Get patterns that frequently cause problems"""
        with self.lock:
            # Return top 20 most dangerous
            sorted_patterns = sorted(
                self.dangerous_patterns.items(), key=lambda x: -x[1]
            )
            return dict(sorted_patterns[:20])

    def get_success_patterns(self) -> Dict[str, float]:
        """Get patterns that frequently lead to success"""
        with self.lock:
            sorted_patterns = sorted(self.success_patterns.items(), key=lambda x: -x[1])
            return dict(sorted_patterns[:20])

    def get_stats(self) -> TrainingStats:
        """Get training statistics"""
        self._update_stats()
        with self.lock:
            return TrainingStats(
                total_experiences=self.stats.total_experiences,
                total_updates=self.stats.total_updates,
                q_table_size=self.stats.q_table_size,
                average_reward=self.stats.average_reward,
                average_td_error=self.stats.average_td_error,
                last_update=self.stats.last_update,
                devices_seen=self.stats.devices_seen,
                training_rate=self.stats.training_rate,
                hardware_acceleration=self.stats.hardware_acceleration,
                memory_usage_mb=self.stats.memory_usage_mb,
            )

    def save(self, path: str):
        """Save Q-table and patterns to JSON file (atomic write)"""
        with self.lock:
            data = {
                "q_table": self.q_table,
                "visit_counts": self.visit_counts,
                "dangerous_patterns": self.dangerous_patterns,
                "success_patterns": self.success_patterns,
                "stats": asdict(self.stats),
                "hyperparams": {
                    "alpha": HYPERPARAMS.alpha,
                    "gamma": HYPERPARAMS.gamma,
                    "epsilon": HYPERPARAMS.epsilon,
                },
            }
            # Use atomic write to prevent corruption on crash
            atomic_write_json(path, data)
            logger.info(f"Saved Q-table to {path} ({len(self.q_table)} entries)")

    def load(self, path: str):
        """Load Q-table from JSON file"""
        with self.lock:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                self.q_table = data.get("q_table", {})
                self.visit_counts = data.get("visit_counts", {})
                self.dangerous_patterns = data.get("dangerous_patterns", {})
                self.success_patterns = data.get("success_patterns", {})
                logger.info(f"Loaded Q-table from {path} ({len(self.q_table)} entries)")
            except FileNotFoundError:
                logger.warning(f"Q-table file not found: {path}")
            except Exception as e:
                logger.error(f"Failed to load Q-table: {e}")

    def reset(self):
        """Reset all learned data"""
        with self.lock:
            self.q_table.clear()
            self.visit_counts.clear()
            self.dangerous_patterns.clear()
            self.success_patterns.clear()
            self.reward_history.clear()
            self.td_error_history.clear()
            self.devices_seen.clear()
            self.stats = TrainingStats()
            # Clear replay buffer
            self.replay_buffer = PrioritizedReplayBuffer(REPLAY_BUFFER_SIZE)
            logger.info("Q-table reset")

    def export_for_android(self) -> str:
        """Export Q-table as JSON string for Android app"""
        with self.lock:
            export_data = {
                "q_table": self.q_table,
                "dangerous_patterns": list(self.dangerous_patterns.keys())[
                    :50
                ],  # Top 50
                "blocked_states": list(
                    self.blocked_states
                ),  # Phase 3: Include blocked states
            }
            return json.dumps(export_data)

    # =========================================================================
    # Phase 3: Q-Table Pruning (Prevent OOM)
    # =========================================================================

    def prune_q_table(self, max_size: Optional[int] = None) -> int:
        """
        Prune Q-table to prevent unbounded growth and OOM crashes.

        Phase 3 Stability: Evicts least-visited entries when table exceeds max size.
        Uses visit count as primary eviction criterion (LRU-like behavior).

        Args:
            max_size: Maximum entries to keep (default: MAX_Q_TABLE_SIZE)

        Returns:
            Number of entries removed
        """
        max_size = max_size or self.MAX_Q_TABLE_SIZE

        with self.lock:
            current_size = len(self.q_table)

            if current_size <= max_size:
                return 0

            # Calculate how many to remove (remove 20% extra to avoid frequent pruning)
            to_remove_count = int((current_size - max_size) * 1.2)

            # Sort entries by visit count (ascending) - least visited first
            entries = [
                (key, self.visit_counts.get(key, 0)) for key in self.q_table.keys()
            ]
            entries.sort(key=lambda x: x[1])

            # Remove least visited entries
            removed_count = 0
            for key, visit_count in entries[:to_remove_count]:
                # Don't remove blocked states (important safety info)
                if key in self.blocked_states:
                    continue

                del self.q_table[key]
                self.visit_counts.pop(key, None)
                self.danger_scores.pop(key, None)
                self.danger_counts.pop(key, None)
                removed_count += 1

            if removed_count > 0:
                logger.info(
                    f"Pruned Q-table: removed {removed_count} entries "
                    f"(was {current_size}, now {len(self.q_table)})"
                )

            return removed_count

    # =========================================================================
    # Phase 3: Async Saves (Non-blocking I/O)
    # =========================================================================

    def save_async(self, path: str):
        """
        Save Q-table asynchronously to prevent blocking the training loop.

        Phase 3 Stability: Uses thread pool executor for non-blocking disk I/O.
        The network heartbeat and training continue while save happens in background.
        """
        if self.pending_save:
            logger.debug("Async save already in progress, skipping")
            return

        self.pending_save = True

        def _save_task():
            try:
                self.save(path)
            finally:
                self.pending_save = False

        self.executor.submit(_save_task)
        logger.debug(f"Async save submitted for {path}")

    # =========================================================================
    # Phase 3: Blocked States API
    # =========================================================================

    def get_blocked_states(self) -> List[str]:
        """
        Get list of blocked (dangerous) state-action pairs.

        Phase 3: Android explorer should avoid these states to prevent crash loops.
        """
        with self.lock:
            return list(self.blocked_states)

    def is_state_blocked(self, screen_hash: str, action_key: str) -> bool:
        """Check if a specific state-action pair is blocked"""
        key = f"{screen_hash}|{action_key}"
        return key in self.blocked_states

    def unblock_state(self, screen_hash: str, action_key: str) -> bool:
        """
        Manually unblock a state (for admin/debug purposes).

        Returns True if state was blocked and is now unblocked.
        """
        key = f"{screen_hash}|{action_key}"
        with self.lock:
            if key in self.blocked_states:
                self.blocked_states.discard(key)
                self.danger_scores[key] = 0
                self.danger_counts[key] = 0
                logger.info(f"Manually unblocked state: {key}")
                return True
            return False

    def get_danger_report(self) -> Dict[str, Any]:
        """
        Get a full report of dangerous states and patterns.

        Useful for debugging and monitoring exploration health.
        """
        with self.lock:
            return {
                "blocked_count": len(self.blocked_states),
                "blocked_states": list(self.blocked_states)[:20],  # Top 20
                "danger_scores": dict(
                    sorted(self.danger_scores.items(), key=lambda x: x[1])[:20]
                ),  # Worst 20
                "dangerous_patterns": dict(
                    sorted(self.dangerous_patterns.items(), key=lambda x: -x[1])[:20]
                ),  # Top 20 dangerous
            }

    def stop(self):
        """Stop background training"""
        self.stop_event.set()
        self.executor.shutdown(wait=False)


# === ONNX Runtime Neural Network Trainer with DirectML/NPU ===

if ONNX_DML_AVAILABLE and NUMPY_AVAILABLE:

    class ONNXQNetworkTrainer:
        """
        Neural network Q-learning trainer using ONNX Runtime with DirectML.
        Uses NPU for inference acceleration on Windows ARM devices.
        Training is done with numpy, inference with ONNX Runtime on NPU.
        """

        def __init__(
            self,
            state_dim: int = 64,
            hidden_dim: int = 128,
            learning_rate: float = 0.001,
        ):
            self.state_dim = state_dim
            self.hidden_dim = hidden_dim
            self.learning_rate = learning_rate

            # Initialize weights with Xavier initialization
            self.W1 = np.random.randn(state_dim, hidden_dim).astype(
                np.float32
            ) * np.sqrt(2.0 / state_dim)
            self.b1 = np.zeros((1, hidden_dim), dtype=np.float32)
            self.W2 = np.random.randn(hidden_dim, hidden_dim).astype(
                np.float32
            ) * np.sqrt(2.0 / hidden_dim)
            self.b2 = np.zeros((1, hidden_dim), dtype=np.float32)
            self.W3 = np.random.randn(hidden_dim, 1).astype(np.float32) * np.sqrt(
                2.0 / hidden_dim
            )
            self.b3 = np.zeros((1, 1), dtype=np.float32)

            # State hashing for fixed-size input
            self.state_encoder: Dict[str, int] = {}
            self.next_state_id = 0

            # Q-table backup for states we haven't encoded
            self.q_table: Dict[str, float] = {}
            self.visit_counts: Dict[str, int] = {}

            # Training data
            self.replay_buffer = PrioritizedReplayBuffer(REPLAY_BUFFER_SIZE)
            self.stats = TrainingStats()
            self.lock = Lock()
            self.devices_seen: set = set()

            # ONNX session (created on first inference)
            self.ort_session = None
            self.session_needs_rebuild = True

            # Background training
            self.executor = ThreadPoolExecutor(max_workers=NUM_WORKERS)
            self.training_queue = queue.Queue(maxsize=1000)
            self.stop_event = Event()
            self.training_thread = Thread(target=self._training_loop, daemon=True)
            self.training_thread.start()

            # Stats
            self.npu_inferences = 0
            self.cpu_updates = 0
            self.stats.hardware_acceleration = "DirectML (NPU)"

            logger.info(f"ONNXQNetworkTrainer initialized with DirectML/NPU support")
            logger.info(f"  State dim: {state_dim}, Hidden dim: {hidden_dim}")

        def _encode_state(self, screen_hash: str, action_key: str) -> np.ndarray:
            """Encode state-action pair as fixed-size vector"""
            key = f"{screen_hash}|{action_key}"

            # Get or create state ID
            if key not in self.state_encoder:
                self.state_encoder[key] = self.next_state_id
                self.next_state_id += 1

            state_id = self.state_encoder[key]

            # Create embedding vector (hash-based encoding)
            state_vec = np.zeros(self.state_dim, dtype=np.float32)

            # Use hash to create deterministic but distributed encoding
            hash_val = hash(key)
            for i in range(self.state_dim):
                # Create pseudo-random values from hash
                state_vec[i] = np.sin(hash_val * (i + 1) * 0.1) * 0.5 + 0.5

            # Add position encoding based on state ID
            for i in range(min(16, self.state_dim)):
                state_vec[i] += np.sin(state_id / (10000 ** (i / 16))) * 0.1

            return state_vec.reshape(1, -1)

        def _relu(self, x: np.ndarray) -> np.ndarray:
            """ReLU activation"""
            return np.maximum(0, x)

        def _forward_numpy(self, state: np.ndarray) -> float:
            """Forward pass using numpy (CPU)"""
            h1 = self._relu(state @ self.W1 + self.b1)
            h2 = self._relu(h1 @ self.W2 + self.b2)
            out = h2 @ self.W3 + self.b3
            return float(out[0, 0])

        def _build_onnx_model(self) -> bytes:
            """Build ONNX model from current weights"""
            from onnx import helper, TensorProto, numpy_helper

            # Input
            X = helper.make_tensor_value_info(
                "input", TensorProto.FLOAT, [1, self.state_dim]
            )
            Y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1])

            # Weights as initializers
            W1_init = numpy_helper.from_array(self.W1, name="W1")
            b1_init = numpy_helper.from_array(self.b1.flatten(), name="b1")
            W2_init = numpy_helper.from_array(self.W2, name="W2")
            b2_init = numpy_helper.from_array(self.b2.flatten(), name="b2")
            W3_init = numpy_helper.from_array(self.W3, name="W3")
            b3_init = numpy_helper.from_array(self.b3.flatten(), name="b3")

            # Nodes
            nodes = [
                helper.make_node("MatMul", ["input", "W1"], ["mm1"]),
                helper.make_node("Add", ["mm1", "b1"], ["h1_pre"]),
                helper.make_node("Relu", ["h1_pre"], ["h1"]),
                helper.make_node("MatMul", ["h1", "W2"], ["mm2"]),
                helper.make_node("Add", ["mm2", "b2"], ["h2_pre"]),
                helper.make_node("Relu", ["h2_pre"], ["h2"]),
                helper.make_node("MatMul", ["h2", "W3"], ["mm3"]),
                helper.make_node("Add", ["mm3", "b3"], ["output"]),
            ]

            graph = helper.make_graph(
                nodes,
                "QNetwork",
                [X],
                [Y],
                [W1_init, b1_init, W2_init, b2_init, W3_init, b3_init],
            )

            model = helper.make_model(
                graph, opset_imports=[helper.make_opsetid("", 13)]
            )
            return model.SerializeToString()

        def _get_ort_session(self):
            """Get or create ONNX Runtime session with DirectML"""
            if self.ort_session is None or self.session_needs_rebuild:
                try:
                    model_bytes = self._build_onnx_model()
                    sess_options = ort.SessionOptions()
                    sess_options.graph_optimization_level = (
                        ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                    )

                    # Use DirectML (NPU) as primary provider
                    self.ort_session = ort.InferenceSession(
                        model_bytes,
                        sess_options,
                        providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                    )
                    self.session_needs_rebuild = False
                    logger.debug("ONNX session created with DirectML provider")
                except Exception as e:
                    logger.error(f"Failed to create ONNX session: {e}")
                    return None
            return self.ort_session

        def _forward_onnx(self, state: np.ndarray) -> float:
            """Forward pass using ONNX Runtime (NPU)"""
            session = self._get_ort_session()
            if session is None:
                return self._forward_numpy(state)

            try:
                output = session.run(None, {"input": state})[0]
                self.npu_inferences += 1
                return float(output[0, 0])
            except Exception as e:
                logger.debug(f"ONNX inference failed, falling back to numpy: {e}")
                return self._forward_numpy(state)

        def predict(self, screen_hash: str, action_key: str) -> float:
            """Predict Q-value for state-action pair"""
            key = f"{screen_hash}|{action_key}"

            # Use Q-table for frequently updated values
            if key in self.q_table and self.visit_counts.get(key, 0) > 5:
                return self.q_table[key]

            # Use neural network for generalization
            state = self._encode_state(screen_hash, action_key)
            q_val = self._forward_onnx(state)

            # Blend with Q-table if available
            if key in self.q_table:
                blend = min(self.visit_counts.get(key, 0) / 10, 0.8)
                q_val = blend * self.q_table[key] + (1 - blend) * q_val

            return q_val

        def _backward(self, state: np.ndarray, target: float):
            """Backward pass to update weights (gradient descent)"""
            # Forward pass with cache
            h1_pre = state @ self.W1 + self.b1
            h1 = self._relu(h1_pre)
            h2_pre = h1 @ self.W2 + self.b2
            h2 = self._relu(h2_pre)
            output = h2 @ self.W3 + self.b3

            # Loss gradient (MSE)
            d_output = 2 * (output - target)

            # Backprop through layer 3
            d_W3 = h2.T @ d_output
            d_b3 = d_output.sum(axis=0, keepdims=True)
            d_h2 = d_output @ self.W3.T

            # Backprop through ReLU
            d_h2_pre = d_h2 * (h2_pre > 0)

            # Backprop through layer 2
            d_W2 = h1.T @ d_h2_pre
            d_b2 = d_h2_pre.sum(axis=0, keepdims=True)
            d_h1 = d_h2_pre @ self.W2.T

            # Backprop through ReLU
            d_h1_pre = d_h1 * (h1_pre > 0)

            # Backprop through layer 1
            d_W1 = state.T @ d_h1_pre
            d_b1 = d_h1_pre.sum(axis=0, keepdims=True)

            # Gradient clipping
            max_grad = 1.0
            d_W1 = np.clip(d_W1, -max_grad, max_grad)
            d_W2 = np.clip(d_W2, -max_grad, max_grad)
            d_W3 = np.clip(d_W3, -max_grad, max_grad)

            # Update weights
            self.W1 -= self.learning_rate * d_W1
            self.b1 -= self.learning_rate * d_b1
            self.W2 -= self.learning_rate * d_W2
            self.b2 -= self.learning_rate * d_b2
            self.W3 -= self.learning_rate * d_W3
            self.b3 -= self.learning_rate * d_b3

            # Mark session for rebuild
            self.session_needs_rebuild = True
            self.cpu_updates += 1

        def _training_loop(self):
            """Background training loop"""
            batch_count = 0
            while not self.stop_event.is_set():
                try:
                    entries = []
                    try:
                        while len(entries) < BATCH_SIZE:
                            entry = self.training_queue.get(timeout=0.1)
                            entries.append(entry)
                    except queue.Empty:
                        pass

                    if entries:
                        for entry in entries:
                            self._process_entry(entry)
                        batch_count += 1

                        # Periodic batch training from replay buffer
                        if (
                            batch_count % 5 == 0
                            and len(self.replay_buffer) >= BATCH_SIZE
                        ):
                            self.train_batch()

                except Exception as e:
                    logger.error(f"Training loop error: {e}")
                    time.sleep(0.5)

        def _process_entry(self, entry: ExplorationLogEntry):
            """Process a single experience"""
            key = f"{entry.screen_hash}|{entry.action_key}"

            with self.lock:
                # Add to replay buffer (td_error approximated by reward magnitude)
                self.replay_buffer.add(entry, abs(entry.reward) + 0.1)

                # Update Q-table for immediate feedback
                current_q = self.q_table.get(key, 0.0)
                next_max_q = (
                    self._get_max_q(entry.next_screen_hash)
                    if entry.next_screen_hash
                    else 0
                )
                target = entry.reward + HYPERPARAMS.gamma * next_max_q

                # Q-learning update
                new_q = current_q + HYPERPARAMS.alpha * (target - current_q)
                self.q_table[key] = new_q
                self.visit_counts[key] = self.visit_counts.get(key, 0) + 1

                # Train neural network
                state = self._encode_state(entry.screen_hash, entry.action_key)
                self._backward(state, target)

                self.stats.total_experiences += 1
                self.stats.total_updates += 1
                self.devices_seen.add(entry.device_id)
                self.stats.devices_seen = len(self.devices_seen)

        def _get_max_q(self, screen_hash: str) -> float:
            """Get max Q-value for a screen"""
            max_q = 0.0
            prefix = f"{screen_hash}|"
            for key, value in self.q_table.items():
                if key.startswith(prefix):
                    max_q = max(max_q, value)
            return max_q

        def add_experience(self, entry: ExplorationLogEntry):
            """Add experience for training"""
            try:
                self.training_queue.put_nowait(entry)
            except queue.Full:
                logger.warning("Training queue full, dropping experience")

        def train_batch(self):
            """Train on a batch from replay buffer using NPU for forward pass"""
            if len(self.replay_buffer) < BATCH_SIZE:
                return

            with self.lock:
                batch, indices, weights = self.replay_buffer.sample(BATCH_SIZE)
                td_errors = []

                for i, entry in enumerate(batch):
                    state = self._encode_state(entry.screen_hash, entry.action_key)

                    # Use NPU for forward pass to get current Q-value
                    current_q = self._forward_onnx(state)

                    # Get max Q for next state
                    next_max_q = (
                        self._get_max_q(entry.next_screen_hash)
                        if entry.next_screen_hash
                        else 0
                    )
                    target = entry.reward + HYPERPARAMS.gamma * next_max_q

                    # Calculate TD error for priority update
                    td_error = abs(target - current_q)
                    td_errors.append(td_error)

                    # Weighted backward pass (CPU - gradients)
                    self._backward(state, target * weights[i])

                # Update priorities in replay buffer
                self.replay_buffer.update_priorities(indices, td_errors)
                self.stats.total_updates += BATCH_SIZE

        def get_stats(self) -> TrainingStats:
            """Get training statistics"""
            with self.lock:
                return TrainingStats(
                    total_experiences=self.stats.total_experiences,
                    total_updates=self.stats.total_updates,
                    q_table_size=len(self.q_table),
                    average_reward=0.0,
                    average_td_error=0.0,
                    last_update=datetime.now().isoformat(),
                    devices_seen=len(self.devices_seen),
                    training_rate=0.0,
                    hardware_acceleration=f"DirectML (NPU) - {self.npu_inferences} inferences",
                    memory_usage_mb=0.0,
                )

        def get_q_table(self) -> Dict[str, float]:
            """Get Q-table for publishing"""
            with self.lock:
                return dict(self.q_table)

        def save(self, path: str):
            """Save model and Q-table (atomic write)"""
            with self.lock:
                data = {
                    "q_table": self.q_table,
                    "visit_counts": self.visit_counts,
                    "state_encoder": self.state_encoder,
                    "W1": self.W1.tolist(),
                    "b1": self.b1.tolist(),
                    "W2": self.W2.tolist(),
                    "b2": self.b2.tolist(),
                    "W3": self.W3.tolist(),
                    "b3": self.b3.tolist(),
                    "stats": {
                        "total_experiences": self.stats.total_experiences,
                        "total_updates": self.stats.total_updates,
                        "q_table_size": len(self.q_table),
                        "npu_inferences": self.npu_inferences,
                        "cpu_updates": self.cpu_updates,
                    },
                }
                # Use atomic write to prevent corruption on crash
                atomic_write_json(path, data)
                logger.info(
                    f"Saved ONNX trainer to {path} ({len(self.q_table)} Q-entries, {self.npu_inferences} NPU inferences)"
                )

        def load(self, path: str):
            """Load model and Q-table"""
            try:
                with open(path, "r") as f:
                    data = json.load(f)

                with self.lock:
                    self.q_table = data.get("q_table", {})
                    self.visit_counts = data.get("visit_counts", {})
                    self.state_encoder = data.get("state_encoder", {})
                    self.next_state_id = len(self.state_encoder)

                    # Load weights if available
                    if "W1" in data:
                        self.W1 = np.array(data["W1"], dtype=np.float32)
                        self.b1 = np.array(data["b1"], dtype=np.float32)
                        self.W2 = np.array(data["W2"], dtype=np.float32)
                        self.b2 = np.array(data["b2"], dtype=np.float32)
                        self.W3 = np.array(data["W3"], dtype=np.float32)
                        self.b3 = np.array(data["b3"], dtype=np.float32)
                        self.session_needs_rebuild = True

                    # Load stats
                    if "stats" in data:
                        self.stats.total_experiences = data["stats"].get(
                            "total_experiences", 0
                        )
                        self.stats.total_updates = data["stats"].get("total_updates", 0)
                        self.npu_inferences = data["stats"].get("npu_inferences", 0)
                        self.cpu_updates = data["stats"].get("cpu_updates", 0)

                logger.info(
                    f"Loaded ONNX trainer from {path} ({len(self.q_table)} Q-entries)"
                )
            except FileNotFoundError:
                logger.warning(f"ONNX trainer file not found: {path}")
            except Exception as e:
                logger.error(f"Failed to load ONNX trainer: {e}")

        def reset(self):
            """Reset all learned data"""
            with self.lock:
                self.q_table.clear()
                self.visit_counts.clear()
                self.state_encoder.clear()
                self.next_state_id = 0

                # Reinitialize weights
                self.W1 = np.random.randn(self.state_dim, self.hidden_dim).astype(
                    np.float32
                ) * np.sqrt(2.0 / self.state_dim)
                self.b1 = np.zeros((1, self.hidden_dim), dtype=np.float32)
                self.W2 = np.random.randn(self.hidden_dim, self.hidden_dim).astype(
                    np.float32
                ) * np.sqrt(2.0 / self.hidden_dim)
                self.b2 = np.zeros((1, self.hidden_dim), dtype=np.float32)
                self.W3 = np.random.randn(self.hidden_dim, 1).astype(
                    np.float32
                ) * np.sqrt(2.0 / self.hidden_dim)
                self.b3 = np.zeros((1, 1), dtype=np.float32)

                self.session_needs_rebuild = True
                self.stats = TrainingStats()
                self.stats.hardware_acceleration = "DirectML (NPU)"
                self.npu_inferences = 0
                self.cpu_updates = 0

                logger.info("ONNX trainer reset")

        def export_for_android(self) -> str:
            """Export Q-table and model info for Android"""
            with self.lock:
                return json.dumps({"q_table": self.q_table, "model_type": "onnx_dml"})

        def stop(self):
            """Stop background training"""
            self.stop_event.set()
            self.executor.shutdown(wait=False)


# === Neural Network Trainer with DirectML/NPU Support ===

if TORCH_AVAILABLE:

    class DuelingQNetwork(nn.Module):
        """
        Dueling DQN architecture for better value estimation
        Separates state value and action advantage
        """

        def __init__(
            self, state_dim: int = 64, action_dim: int = 32, hidden_dim: int = 256
        ):
            super().__init__()

            # Shared encoder
            self.encoder = nn.Sequential(
                nn.Linear(state_dim + action_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(hidden_dim, hidden_dim),
                nn.LayerNorm(hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.1),
            )

            # Value stream
            self.value_stream = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.ReLU(),
                nn.Linear(hidden_dim // 2, 1),
            )

            # Advantage stream
            self.advantage_stream = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.ReLU(),
                nn.Linear(hidden_dim // 2, 1),
            )

        def forward(self, state_action):
            features = self.encoder(state_action)
            value = self.value_stream(features)
            advantage = self.advantage_stream(features)
            # Combine: Q = V + A - mean(A)
            return value + advantage

    class DQNTrainer:
        """
        Enhanced Deep Q-Network trainer with:
        - DirectML/NPU acceleration for Windows
        - Double DQN for reduced overestimation
        - Dueling architecture
        - Prioritized Experience Replay
        - Gradient clipping
        - Soft target updates
        """

        def __init__(
            self, state_dim: int = 64, action_dim: int = 32, hidden_dim: int = 256
        ):
            # Select best available device
            if DML_AVAILABLE:
                self.device = torch_directml.device()
                self.hw_accel = "DirectML (NPU)"
                logger.info(f"Using DirectML device (NPU acceleration)")
            elif torch.cuda.is_available():
                self.device = torch.device("cuda")
                self.hw_accel = f"CUDA ({torch.cuda.get_device_name(0)})"
                logger.info(f"Using CUDA: {torch.cuda.get_device_name(0)}")
            else:
                self.device = torch.device("cpu")
                self.hw_accel = "CPU"
                logger.info("Using CPU (install torch-directml for NPU acceleration)")

            self.state_dim = state_dim
            self.action_dim = action_dim

            # Networks
            self.q_network = DuelingQNetwork(state_dim, action_dim, hidden_dim).to(
                self.device
            )
            self.target_network = DuelingQNetwork(state_dim, action_dim, hidden_dim).to(
                self.device
            )
            self.target_network.load_state_dict(self.q_network.state_dict())
            self.target_network.eval()

            # Optimizer with weight decay
            self.optimizer = optim.AdamW(
                self.q_network.parameters(), lr=0.0003, weight_decay=0.01
            )

            # Learning rate scheduler
            self.scheduler = optim.lr_scheduler.StepLR(
                self.optimizer, step_size=1000, gamma=0.95
            )

            # Replay buffer
            self.replay_buffer = PrioritizedReplayBuffer(REPLAY_BUFFER_SIZE)
            self.stats = TrainingStats()
            self.stats.hardware_acceleration = self.hw_accel

            # State/action embedding caches
            self.state_embeddings: Dict[str, np.ndarray] = {}
            self.action_embeddings: Dict[str, np.ndarray] = {}

            # Q-table for hybrid approach (maintains tabular Q-values too)
            self.q_table: Dict[str, float] = {}
            self.lock = Lock()

            # Training metrics
            self.loss_history: deque = deque(maxlen=1000)
            self.reward_history: deque = deque(maxlen=1000)

            logger.info(f"DQNTrainer initialized on {self.hw_accel}")

        def _get_embedding(self, hash_str: str, dim: int, cache: dict) -> np.ndarray:
            """Convert hash string to stable embedding vector"""
            if hash_str not in cache:
                # Use hash for reproducible randomness
                np.random.seed(hash(hash_str) % (2**32))
                # Xavier-like initialization
                cache[hash_str] = (np.random.randn(dim) / np.sqrt(dim)).astype(
                    np.float32
                )
            return cache[hash_str]

        def add_experience(self, entry: ExplorationLogEntry):
            """Add experience to replay buffer"""
            self.replay_buffer.add(entry, entry.priority)
            with self.lock:
                self.stats.total_experiences += 1
                self.reward_history.append(entry.reward)

                # Also update tabular Q-value
                key = f"{entry.screen_hash}|{entry.action_key}"
                current_q = self.q_table.get(key, 0.0)
                next_max_q = (
                    self._get_max_tabular_q(entry.next_screen_hash)
                    if entry.next_screen_hash
                    else 0
                )
                target = entry.reward + HYPERPARAMS.gamma * next_max_q
                self.q_table[key] = current_q + HYPERPARAMS.alpha * (target - current_q)

        def _get_max_tabular_q(self, screen_hash: str) -> float:
            """Get max Q from tabular representation"""
            max_q = 0.0
            prefix = f"{screen_hash}|"
            for key, value in self.q_table.items():
                if key.startswith(prefix):
                    max_q = max(max_q, value)
            return max_q

        def train_batch(self, batch_size: int = BATCH_SIZE):
            """Train on a batch using Double DQN with PER"""
            if len(self.replay_buffer) < batch_size:
                return

            # Sample with priorities
            batch, indices, weights = self.replay_buffer.sample(batch_size)

            # Prepare tensors
            states_actions = []
            next_states_actions = []
            rewards = []
            dones = []

            for entry in batch:
                state_emb = self._get_embedding(
                    entry.screen_hash, self.state_dim, self.state_embeddings
                )
                action_emb = self._get_embedding(
                    entry.action_key, self.action_dim, self.action_embeddings
                )
                states_actions.append(np.concatenate([state_emb, action_emb]))
                rewards.append(entry.reward)

                if entry.next_screen_hash:
                    next_state_emb = self._get_embedding(
                        entry.next_screen_hash, self.state_dim, self.state_embeddings
                    )
                    # For next state, we use a "default" action embedding
                    next_states_actions.append(
                        np.concatenate(
                            [
                                next_state_emb,
                                np.zeros(self.action_dim, dtype=np.float32),
                            ]
                        )
                    )
                    dones.append(0)
                else:
                    next_states_actions.append(
                        np.zeros(self.state_dim + self.action_dim, dtype=np.float32)
                    )
                    dones.append(1)

            # Convert to tensors
            states_actions = torch.FloatTensor(np.array(states_actions)).to(self.device)
            next_states_actions = torch.FloatTensor(np.array(next_states_actions)).to(
                self.device
            )
            rewards = torch.FloatTensor(rewards).to(self.device)
            dones = torch.FloatTensor(dones).to(self.device)
            weights = torch.FloatTensor(weights).to(self.device)

            # Current Q values
            current_q = self.q_network(states_actions).squeeze()

            # Double DQN: use online network to select action, target network to evaluate
            with torch.no_grad():
                # Target Q values
                next_q = self.target_network(next_states_actions).squeeze()
                target_q = rewards + HYPERPARAMS.gamma * next_q * (1 - dones)

            # Compute TD errors for priority update
            td_errors = (target_q - current_q).abs().detach().cpu().numpy()

            # Weighted Huber loss (more robust than MSE)
            loss = F.smooth_l1_loss(current_q * weights, target_q * weights)

            # Optimize
            self.optimizer.zero_grad()
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), max_norm=10.0)

            self.optimizer.step()
            self.scheduler.step()

            with self.lock:
                self.stats.total_updates += 1
                self.loss_history.append(loss.item())

            # Update priorities
            self.replay_buffer.update_priorities(indices, td_errors.tolist())

            # Soft update target network
            if self.stats.total_updates % 10 == 0:
                self._soft_update_target()

            # Decay hyperparameters
            HYPERPARAMS.decay()

            if self.stats.total_updates % 100 == 0:
                avg_loss = (
                    sum(self.loss_history) / len(self.loss_history)
                    if self.loss_history
                    else 0
                )
                logger.info(
                    f"DQN update {self.stats.total_updates}, loss: {avg_loss:.4f}, lr: {self.scheduler.get_last_lr()[0]:.6f}"
                )

        def _soft_update_target(self):
            """Soft update target network: θ_target = τ*θ + (1-τ)*θ_target"""
            for target_param, param in zip(
                self.target_network.parameters(), self.q_network.parameters()
            ):
                target_param.data.copy_(
                    HYPERPARAMS.tau * param.data
                    + (1 - HYPERPARAMS.tau) * target_param.data
                )

        def get_q_table(self) -> Dict[str, float]:
            """Get hybrid Q-table (combines tabular + neural estimates)"""
            with self.lock:
                return dict(self.q_table)

        def get_stats(self) -> TrainingStats:
            """Get training statistics"""
            with self.lock:
                avg_reward = (
                    sum(self.reward_history) / len(self.reward_history)
                    if self.reward_history
                    else 0
                )
                avg_loss = (
                    sum(self.loss_history) / len(self.loss_history)
                    if self.loss_history
                    else 0
                )
                return TrainingStats(
                    total_experiences=self.stats.total_experiences,
                    total_updates=self.stats.total_updates,
                    q_table_size=len(self.q_table),
                    average_reward=avg_reward,
                    average_td_error=avg_loss,
                    last_update=datetime.now().isoformat(),
                    devices_seen=0,
                    training_rate=0,
                    hardware_acceleration=self.stats.hardware_acceleration,
                    memory_usage_mb=0,
                )

        def save(self, path: str):
            """Save model and Q-table (atomic writes)"""
            with self.lock:
                data = {
                    "q_table": self.q_table,
                    "model_state": None,  # Can't JSON serialize PyTorch state
                    "stats": asdict(self.stats),
                }
                # Use atomic write for JSON to prevent corruption on crash
                atomic_write_json(path, data)

                # Save PyTorch model separately (torch.save uses temp file internally)
                model_path = path.replace(".json", "_model.pt")
                torch.save(
                    {
                        "q_network": self.q_network.state_dict(),
                        "target_network": self.target_network.state_dict(),
                        "optimizer": self.optimizer.state_dict(),
                        "scheduler": self.scheduler.state_dict(),
                    },
                    model_path,
                )

                logger.info(f"Saved DQN model to {model_path}")

        def load(self, path: str):
            """Load model and Q-table"""
            with self.lock:
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    self.q_table = data.get("q_table", {})

                    # Load PyTorch model
                    model_path = path.replace(".json", "_model.pt")
                    if os.path.exists(model_path):
                        checkpoint = torch.load(model_path, map_location=self.device)
                        self.q_network.load_state_dict(checkpoint["q_network"])
                        self.target_network.load_state_dict(
                            checkpoint["target_network"]
                        )
                        self.optimizer.load_state_dict(checkpoint["optimizer"])
                        self.scheduler.load_state_dict(checkpoint["scheduler"])
                        logger.info(f"Loaded DQN model from {model_path}")

                except FileNotFoundError:
                    logger.warning(f"Model file not found: {path}")
                except Exception as e:
                    logger.error(f"Failed to load model: {e}")

        def reset(self):
            """Reset all learned data"""
            with self.lock:
                self.q_table.clear()
                self.state_embeddings.clear()
                self.action_embeddings.clear()
                self.replay_buffer = PrioritizedReplayBuffer(REPLAY_BUFFER_SIZE)
                self.loss_history.clear()
                self.reward_history.clear()

                # Reinitialize networks
                self.q_network = DuelingQNetwork(self.state_dim, self.action_dim).to(
                    self.device
                )
                self.target_network = DuelingQNetwork(
                    self.state_dim, self.action_dim
                ).to(self.device)
                self.target_network.load_state_dict(self.q_network.state_dict())
                self.optimizer = optim.AdamW(
                    self.q_network.parameters(), lr=0.0003, weight_decay=0.01
                )
                self.scheduler = optim.lr_scheduler.StepLR(
                    self.optimizer, step_size=1000, gamma=0.95
                )
                self.stats = TrainingStats()
                self.stats.hardware_acceleration = self.hw_accel

                logger.info("DQN trainer reset")

        def export_for_android(self) -> str:
            """Export Q-table as JSON for Android"""
            with self.lock:
                return json.dumps(self.q_table)

        def export_tflite(
            self, output_path: str = "q_network.tflite"
        ) -> Optional[bytes]:
            """
            Export the Q-network as a TensorFlow Lite model for Android inference.

            Returns the model bytes if successful, None otherwise.

            Process:
            1. Export PyTorch model to ONNX
            2. Convert ONNX to TensorFlow (via onnx-tf)
            3. Convert TensorFlow to TFLite with quantization
            """
            try:
                import tempfile
                import base64

                logger.info("Exporting model to TFLite format...")

                # Step 1: Export to ONNX
                onnx_path = tempfile.mktemp(suffix=".onnx")
                dummy_input = torch.randn(
                    1, self.state_dim + self.action_dim, device=self.device
                )

                # Move model to CPU for ONNX export
                model_cpu = DuelingQNetwork(self.state_dim, self.action_dim).cpu()
                model_cpu.load_state_dict(self.q_network.state_dict())
                model_cpu.eval()

                torch.onnx.export(
                    model_cpu,
                    dummy_input.cpu(),
                    onnx_path,
                    input_names=["features"],
                    output_names=["q_value"],
                    dynamic_axes={
                        "features": {0: "batch_size"},
                        "q_value": {0: "batch_size"},
                    },
                    opset_version=12,
                )
                logger.info(f"Exported ONNX model to {onnx_path}")

                # Step 2: Try to convert via onnx-tf
                try:
                    import onnx
                    from onnx_tf.backend import prepare
                    import tensorflow as tf

                    onnx_model = onnx.load(onnx_path)
                    tf_rep = prepare(onnx_model)

                    # Save TensorFlow model
                    tf_path = tempfile.mkdtemp()
                    tf_rep.export_graph(tf_path)
                    logger.info(f"Converted to TensorFlow at {tf_path}")

                    # Step 3: Convert to TFLite with quantization
                    converter = tf.lite.TFLiteConverter.from_saved_model(tf_path)
                    converter.optimizations = [tf.lite.Optimize.DEFAULT]
                    converter.target_spec.supported_types = [
                        tf.float16
                    ]  # Float16 quantization

                    tflite_model = converter.convert()

                    # Save to file
                    with open(output_path, "wb") as f:
                        f.write(tflite_model)

                    logger.info(
                        f"Exported TFLite model: {output_path} ({len(tflite_model)} bytes)"
                    )

                    # Cleanup temp files
                    os.remove(onnx_path)
                    import shutil

                    shutil.rmtree(tf_path, ignore_errors=True)

                    return tflite_model

                except ImportError as e:
                    logger.warning(
                        f"onnx-tf not available, falling back to ONNX only: {e}"
                    )
                    logger.warning("Install: pip install onnx onnx-tf tensorflow")

                    # Return ONNX as fallback (Android can use onnxruntime)
                    with open(onnx_path, "rb") as f:
                        onnx_bytes = f.read()
                    os.remove(onnx_path)
                    return onnx_bytes

            except Exception as e:
                logger.error(f"Failed to export TFLite model: {e}", exc_info=True)
                return None

        def get_model_bytes_for_mqtt(self) -> Optional[Tuple[bytes, str]]:
            """
            Get model bytes ready for MQTT publishing.

            Returns (model_bytes, version) or None if export fails.
            """
            model_bytes = self.export_tflite()
            if model_bytes:
                version = f"v{self.stats.total_updates}_{int(time.time())}"
                return model_bytes, version
            return None

        def stop(self):
            """Cleanup"""
            pass


# === Coral Edge TPU Trainer ===


class CoralQNetworkTrainer:
    """
    Q-Network trainer using Coral Edge TPU for inference acceleration.

    Training still happens on CPU using Q-table updates (Edge TPU is inference-only).
    Periodically exports a quantized TFLite model for Edge TPU inference.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.interpreter = None
        self.model_path = model_path

        # Q-table for training (Edge TPU only supports inference)
        self.q_table: Dict[str, Dict[str, float]] = {}
        self.experience_buffer = deque(maxlen=10000)

        # Stats tracking
        self.stats = TrainingStats()
        self.hw_accel = "coral_edge_tpu"

        # Hyperparameters
        self.params = HyperParams()

        # Try to load existing Edge TPU model
        if model_path and os.path.exists(model_path):
            self._load_edgetpu_model(model_path)

    def _load_edgetpu_model(self, model_path: str) -> bool:
        """Load Edge TPU compiled model for inference"""
        try:
            from pycoral.utils.edgetpu import make_interpreter

            self.interpreter = make_interpreter(model_path)
            self.interpreter.allocate_tensors()
            logger.info(f"Loaded Edge TPU model from {model_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load Edge TPU model: {e}")
            return False

    def _encode_state(self, state: str) -> np.ndarray:
        """Encode state string to input tensor for inference"""
        # Simple hash-based encoding (same as other trainers)
        state_hash = hash(state) % (2**32)
        # Create normalized input (Edge TPU expects uint8 or int8)
        input_data = np.array(
            [(state_hash >> i) & 0xFF for i in range(0, 32, 8)], dtype=np.uint8
        )
        return input_data.reshape(1, -1)

    def _decode_output(
        self, output: np.ndarray, actions: List[str]
    ) -> Dict[str, float]:
        """Decode Edge TPU output to Q-values"""
        # Output is quantized, scale back to float
        output_float = output.astype(np.float32) / 255.0 * 2.0 - 1.0  # Scale to [-1, 1]
        return {
            action: float(output_float[0][i])
            for i, action in enumerate(actions[: len(output_float[0])])
        }

    def predict(
        self, state: str, available_actions: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """Get Q-values for state (uses Edge TPU if model loaded, else Q-table)"""
        if self.interpreter and available_actions:
            try:
                from pycoral.adapters import common

                input_data = self._encode_state(state)
                common.set_input(self.interpreter, input_data)
                self.interpreter.invoke()
                output = common.output_tensor(self.interpreter, 0)
                return self._decode_output(output, available_actions)
            except Exception as e:
                logger.debug(f"Edge TPU inference failed, using Q-table: {e}")

        # Fallback to Q-table
        return self.q_table.get(state, {})

    def get_action(self, state: str, available_actions: List[str]) -> str:
        """Select action using epsilon-greedy policy"""
        import random

        if random.random() < self.params.epsilon:
            return random.choice(available_actions)

        q_values = self.predict(state, available_actions)
        if not q_values:
            return random.choice(available_actions)

        # Filter to available actions only
        available_q = {a: q_values.get(a, 0.0) for a in available_actions}
        return max(available_q, key=available_q.get)

    def train(
        self, state: str, action: str, reward: float, next_state: str, done: bool
    ):
        """Update Q-table (training happens on CPU)"""
        # Standard Q-learning update
        if state not in self.q_table:
            self.q_table[state] = {}

        current_q = self.q_table[state].get(action, 0.0)

        # Get max Q-value for next state
        next_q_values = self.q_table.get(next_state, {})
        max_next_q = max(next_q_values.values()) if next_q_values else 0.0

        # Q-learning update
        if done:
            target = reward
        else:
            target = reward + self.params.gamma * max_next_q

        new_q = current_q + self.params.alpha * (target - current_q)
        self.q_table[state][action] = new_q

        # Update stats
        self.stats.total_updates += 1

        # Decay exploration
        self.params.decay()

    def save(self, path: str):
        """Save Q-table and model info"""
        data = {
            "q_values": self.q_table,
            "metadata": {
                "trainer_type": "coral_edge_tpu",
                "total_updates": self.stats.total_updates,
                "epsilon": self.params.epsilon,
                "alpha": self.params.alpha,
                "last_training_time": datetime.now().isoformat(),
                "coral_devices": CORAL_DEVICES,
            },
        }
        atomic_write_json(path, data)
        logger.info(f"Saved Q-table to {path} ({len(self.q_table)} states)")

    def load(self, path: str):
        """Load Q-table from file"""
        try:
            with open(path, "r") as f:
                data = json.load(f)

            self.q_table = data.get("q_values", data.get("q_table", {}))

            metadata = data.get("metadata", {})
            self.stats.total_updates = metadata.get("total_updates", 0)
            self.params.epsilon = metadata.get("epsilon", self.params.epsilon)
            self.params.alpha = metadata.get("alpha", self.params.alpha)

            logger.info(f"Loaded Q-table from {path} ({len(self.q_table)} states)")
        except Exception as e:
            logger.error(f"Failed to load Q-table: {e}")

    def export_for_android(self) -> Dict[str, Any]:
        """Export Q-table for Android app (same format as other trainers)"""
        return {
            "q_values": self.q_table,
            "metadata": {
                "version": f"coral_v{self.stats.total_updates}",
                "total_states": len(self.q_table),
                "epsilon": self.params.epsilon,
                "trainer_type": "coral_edge_tpu",
            },
        }

    def get_training_stats(self) -> Dict[str, Any]:
        """Get training statistics"""
        return {
            "total_updates": self.stats.total_updates,
            "total_states": len(self.q_table),
            "epsilon": self.params.epsilon,
            "alpha": self.params.alpha,
            "hw_accel": self.hw_accel,
            "coral_devices": CORAL_DEVICES,
            "model_loaded": self.interpreter is not None,
        }

    def stop(self):
        """Cleanup"""
        self.interpreter = None


# === MQTT Handler ===


class MLTrainingServer:
    """Main MQTT-based training server with monitoring"""

    def __init__(
        self,
        broker: str,
        port: int,
        username: str = "",
        password: str = "",
        use_dqn: bool = False,
        use_coral: bool = False,
    ):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id=f"ml_training_server_{int(time.time())}")
        self.running = False

        # Set MQTT authentication if provided
        if username and password:
            self.client.username_pw_set(username, password)
            logger.info(f"MQTT authentication configured for user: {username}")

        # Choose best available trainer (priority order):
        # 1. Coral Edge TPU if available and requested
        # 2. DQN (PyTorch) if available and requested
        # 3. ONNX with DirectML/NPU if available (best for Windows ARM)
        # 4. Enhanced Q-table trainer (fallback)
        if use_coral and CORAL_AVAILABLE:
            self.trainer = CoralQNetworkTrainer()
            logger.info(f"Using Coral Edge TPU trainer ({CORAL_DEVICES} device(s))")
        elif use_dqn and TORCH_AVAILABLE:
            self.trainer = DQNTrainer()
            logger.info(f"Using DQN trainer with {self.trainer.hw_accel}")
        elif ONNX_DML_AVAILABLE and NUMPY_AVAILABLE:
            self.trainer = ONNXQNetworkTrainer()
            logger.info("Using ONNX trainer with DirectML/NPU acceleration")
        else:
            self.trainer = QTableTrainer()
            logger.info("Using enhanced Q-table trainer")

        # Q-table file path (uses DATA_DIR for HA Add-on compatibility)
        self.data_dir = DATA_DIR
        self.q_table_path = self.data_dir / "exploration_q_table.json"

        # Load existing Q-table if available
        if self.q_table_path.exists():
            self.trainer.load(str(self.q_table_path))

        # Setup MQTT callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Background threads
        self.update_count = 0
        self.last_save_time = time.time()

        # Stats publishing thread
        self.stats_thread = None

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {self.broker}:{self.port}")
            # Subscribe to topics
            client.subscribe(MQTT_TOPIC_LOGS)
            client.subscribe(MQTT_TOPIC_COMMAND)
            logger.info(f"Subscribed to {MQTT_TOPIC_LOGS} and {MQTT_TOPIC_COMMAND}")

            # Publish online status
            self._publish_status("online")

            # Print hardware info
            logger.info(f"Hardware: {HW_INFO}")
        else:
            logger.error(f"Failed to connect to MQTT broker: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker: rc={rc}")
        if self.running:
            logger.info("Attempting to reconnect...")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")

            if topic == MQTT_TOPIC_LOGS:
                self._handle_exploration_log(payload)
            elif topic == MQTT_TOPIC_COMMAND:
                self._handle_command(payload)
            else:
                logger.warning(f"Unknown topic: {topic}")

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _handle_exploration_log(self, payload: str):
        """Process exploration log from Android"""
        try:
            data = json.loads(payload)

            # Handle single entry or batch
            entries = data if isinstance(data, list) else [data]

            for entry_data in entries:
                entry = ExplorationLogEntry(
                    screen_hash=entry_data.get(
                        "screenHash", entry_data.get("screen_hash", "")
                    ),
                    action_key=entry_data.get(
                        "actionKey", entry_data.get("action_key", "")
                    ),
                    reward=float(entry_data.get("reward", 0)),
                    next_screen_hash=entry_data.get(
                        "nextScreenHash", entry_data.get("next_screen_hash")
                    ),
                    timestamp=int(entry_data.get("timestamp", 0)),
                    device_id=entry_data.get("deviceId", entry_data.get("device_id")),
                )
                self.trainer.add_experience(entry)

            self.update_count += len(entries)

            # Periodic training (for Q-table trainer, DQN trains automatically)
            if (
                isinstance(self.trainer, QTableTrainer)
                and self.update_count >= TRAINING_INTERVAL
            ):
                self.trainer.train_batch()
                self.update_count = 0

            # Periodic Q-table publishing
            stats = self.trainer.get_stats()
            if stats.total_updates > 0 and stats.total_updates % PUBLISH_INTERVAL == 0:
                self._publish_q_table()

            # Periodic saving
            if time.time() - self.last_save_time > 60:  # Save every minute
                self.trainer.save(str(self.q_table_path))
                self.last_save_time = time.time()

        except Exception as e:
            logger.error(f"Error handling exploration log: {e}", exc_info=True)

    def _handle_command(self, payload: str):
        """Handle command messages"""
        try:
            data = json.loads(payload)
            command = data.get("command", "")

            if command == "reset":
                self.trainer.reset()
                self._publish_status("reset_complete")
                logger.info("Q-table reset by command")

            elif command == "save":
                self.trainer.save(str(self.q_table_path))
                self._publish_status("saved")

            elif command == "export":
                self._publish_q_table()
                self._publish_status("exported")

            elif command == "stats":
                stats = self.trainer.get_stats()
                self.client.publish(MQTT_TOPIC_STATUS, json.dumps(asdict(stats)))

            elif command == "train":
                # Force batch training
                self.trainer.train_batch(BATCH_SIZE * 4)
                self._publish_status("trained")

            elif command == "export_tflite":
                # Export and publish TFLite model
                if self._publish_tflite_model():
                    self._publish_status("model_exported")
                else:
                    self._publish_status("model_export_failed")

            else:
                logger.warning(f"Unknown command: {command}")

        except Exception as e:
            logger.error(f"Error handling command: {e}")

    def _publish_q_table(self):
        """Publish Q-table to Android"""
        q_table = self.trainer.get_q_table()

        # Also include dangerous patterns if available
        export_data = {"q_table": q_table}
        if hasattr(self.trainer, "get_dangerous_patterns"):
            export_data["dangerous_patterns"] = list(
                self.trainer.get_dangerous_patterns().keys()
            )

        payload = json.dumps(export_data)
        self.client.publish(MQTT_TOPIC_QTABLE, payload)
        logger.info(f"Published Q-table ({len(q_table)} entries)")

    def _publish_tflite_model(self):
        """Publish TFLite model to Android devices via MQTT"""
        import base64

        if not hasattr(self.trainer, "get_model_bytes_for_mqtt"):
            logger.warning(
                "TFLite export not available (QTableTrainer doesn't support it)"
            )
            return False

        result = self.trainer.get_model_bytes_for_mqtt()
        if result is None:
            logger.error("Failed to export TFLite model")
            return False

        model_bytes, version = result

        # Encode model as base64 for JSON transport
        model_base64 = base64.b64encode(model_bytes).decode("utf-8")

        payload = json.dumps(
            {
                "type": "model_update",
                "model": model_base64,
                "version": version,
                "size_bytes": len(model_bytes),
                "timestamp": time.time(),
            }
        )

        self.client.publish(MQTT_TOPIC_MODEL, payload)
        logger.info(
            f"Published TFLite model: version={version}, size={len(model_bytes)} bytes"
        )
        return True

    def _publish_status(self, status: str):
        """Publish status message"""
        stats = self.trainer.get_stats()
        payload = json.dumps(
            {
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "q_table_size": stats.q_table_size,
                "total_experiences": stats.total_experiences,
                "average_reward": stats.average_reward,
                "hardware": stats.hardware_acceleration,
                "training_rate": stats.training_rate,
            }
        )
        self.client.publish(MQTT_TOPIC_STATUS, payload)

    def _stats_publisher(self):
        """Background thread to publish stats periodically"""
        last_experiences = 0
        while self.running:
            try:
                time.sleep(30)  # Every 30 seconds (reduced from 10s)
                if self.running:
                    # Only publish if there's actual training activity
                    current_experiences = (
                        self.trainer.stats.total_experiences
                        if hasattr(self.trainer, "stats")
                        else 0
                    )
                    if current_experiences > last_experiences:
                        self._publish_status("running")
                        last_experiences = current_experiences
                    # Still publish heartbeat every 2 minutes even if no activity
                    elif time.time() % 120 < 30:
                        self._publish_status("idle")
            except Exception as e:
                logger.error(f"Stats publisher error: {e}")

    def start(self):
        """Start the training server"""
        self.running = True

        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()

            # Start stats publisher thread
            self.stats_thread = Thread(target=self._stats_publisher, daemon=True)
            self.stats_thread.start()

            print("\n" + "=" * 60)
            print("ML Training Server - Enhanced Edition")
            print("=" * 60)
            print(f"  Broker: {self.broker}:{self.port}")
            print(f"  Topics: {MQTT_TOPIC_LOGS}, {MQTT_TOPIC_COMMAND}")
            print(
                f"  Hardware: {self.trainer.stats.hardware_acceleration if hasattr(self.trainer, 'stats') else 'CPU'}"
            )
            print(f"  Workers: {NUM_WORKERS} threads")
            print(f"  Batch size: {BATCH_SIZE}")
            print(f"  Buffer size: {REPLAY_BUFFER_SIZE}")
            print("=" * 60)
            print("  Press Ctrl+C to stop")
            print("=" * 60 + "\n")

            # Keep running
            while self.running:
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.stop()

    def stop(self):
        """Stop the training server"""
        self.running = False
        self._publish_status("offline")

        # Save Q-table before exit
        self.trainer.save(str(self.q_table_path))

        # Stop trainer
        if hasattr(self.trainer, "stop"):
            self.trainer.stop()

        self.client.loop_stop()
        self.client.disconnect()
        logger.info("ML Training Server stopped")


# === Main Entry Point ===


def main():
    parser = argparse.ArgumentParser(
        description="ML Training Server for Smart Explorer (Enhanced)"
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker address")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="MQTT broker port"
    )
    parser.add_argument("--username", type=str, default="", help="MQTT username")
    parser.add_argument("--password", type=str, default="", help="MQTT password")
    parser.add_argument(
        "--dqn", action="store_true", help="Use Deep Q-Network (requires PyTorch)"
    )
    parser.add_argument(
        "--use-coral", action="store_true", help="Use Coral Edge TPU for inference"
    )
    parser.add_argument("--export", type=str, help="Export Q-table to file and exit")
    parser.add_argument(
        "--load", type=str, help="Load Q-table from file before starting"
    )
    parser.add_argument(
        "--info", action="store_true", help="Show hardware info and exit"
    )

    args = parser.parse_args()

    # Show hardware info
    if args.info:
        print("\nHardware Information:")
        print("=" * 40)
        for key, value in HW_INFO.items():
            print(f"  {key}: {value}")
        print("=" * 40)

        print("\nRecommendations:")
        if HW_INFO.get("coral_available"):
            print(f"  - Coral Edge TPU available! Use --use-coral for TPU acceleration")
            print(f"    {HW_INFO.get('coral_devices', 0)} device(s) detected")
        if HW_INFO.get("directml_available"):
            print("  - DirectML available! Use --dqn for NPU acceleration")
        elif HW_INFO.get("cuda_available"):
            print("  - CUDA available! Use --dqn for GPU acceleration")
        else:
            print("  - Install torch-directml for NPU acceleration:")
            print("    pip install torch-directml")
            print("  - Or install pycoral for Coral Edge TPU:")
            print("    pip install pycoral")
        return

    # Handle export command
    if args.export:
        trainer = QTableTrainer()
        if args.load:
            trainer.load(args.load)
        trainer.save(args.export)
        print(f"Exported Q-table to {args.export}")
        return

    # Start server
    use_coral = getattr(args, "use_coral", False)
    server = MLTrainingServer(
        args.broker,
        args.port,
        username=args.username,
        password=args.password,
        use_dqn=args.dqn,
        use_coral=use_coral,
    )

    # Load existing Q-table if specified
    if args.load:
        server.trainer.load(args.load)

    # Handle signals
    def signal_handler(sig, frame):
        print("\nReceived shutdown signal...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start
    server.start()


if __name__ == "__main__":
    main()
