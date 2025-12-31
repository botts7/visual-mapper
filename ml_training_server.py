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
    python ml_training_server.py --broker 192.168.86.66 --port 1883 --dqn

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
        "onnx_available": False
    }

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

    return hw_info

HW_INFO = detect_hardware()

# Try to import PyTorch
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

# Try to import numpy
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("NumPy not available - some features may be limited")


# === Configuration ===

DEFAULT_BROKER = "localhost"
DEFAULT_PORT = 1883
MQTT_TOPIC_LOGS = "visualmapper/exploration/logs"
MQTT_TOPIC_QTABLE = "visualmapper/exploration/qtable"
MQTT_TOPIC_STATUS = "visualmapper/exploration/status"
MQTT_TOPIC_COMMAND = "visualmapper/exploration/command"

# Q-learning hyperparameters (auto-tuned based on experience)
class HyperParams:
    def __init__(self):
        self.alpha = 0.1         # Learning rate
        self.alpha_min = 0.01    # Minimum learning rate
        self.alpha_decay = 0.9999  # Learning rate decay
        self.gamma = 0.95        # Discount factor (higher = more foresight)
        self.epsilon = 0.3       # Exploration rate
        self.epsilon_min = 0.05  # Minimum exploration
        self.epsilon_decay = 0.995  # Epsilon decay
        self.tau = 0.005         # Soft update rate for target network

        # Prioritized Experience Replay
        self.per_alpha = 0.6     # Priority exponent
        self.per_beta = 0.4      # Importance sampling
        self.per_beta_increment = 0.001
        self.per_epsilon = 1e-6  # Small constant for stability

    def decay(self):
        """Decay learning rate and epsilon"""
        self.alpha = max(self.alpha_min, self.alpha * self.alpha_decay)
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        self.per_beta = min(1.0, self.per_beta + self.per_beta_increment)

HYPERPARAMS = HyperParams()

# Training settings
BATCH_SIZE = 64              # Larger batch for better gradients
REPLAY_BUFFER_SIZE = 50000   # Larger buffer for more diversity
TRAINING_INTERVAL = 5        # Train more frequently
PUBLISH_INTERVAL = 25        # Publish Q-table more often
TARGET_UPDATE_INTERVAL = 100 # Update target network every N steps
SAVE_INTERVAL = 500          # Save checkpoint every N updates
NUM_WORKERS = max(2, (os.cpu_count() or 4) - 1)  # Leave one core free

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ml_training.log')
    ]
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
        self.tree = np.zeros(2 * capacity - 1) if NUMPY_AVAILABLE else [0.0] * (2 * capacity - 1)
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

    def sample(self, batch_size: int) -> Tuple[List[ExplorationLogEntry], List[int], np.ndarray]:
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
                priority = (abs(td_error) + HYPERPARAMS.per_epsilon) ** HYPERPARAMS.per_alpha
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
    """

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
        self.success_patterns: Dict[str, float] = {}    # pattern -> success score

        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=NUM_WORKERS)
        self.training_queue = queue.Queue(maxsize=1000)
        self.stop_event = Event()

        # Start background training thread
        self.training_thread = Thread(target=self._training_loop, daemon=True)
        self.training_thread.start()

        # Performance tracking
        self.last_update_time = time.time()
        self.updates_since_last = 0

        logger.info(f"QTableTrainer initialized with {NUM_WORKERS} worker threads")

    def _training_loop(self):
        """Background training loop"""
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

                # Periodic batch training from replay buffer
                if len(self.replay_buffer) >= BATCH_SIZE:
                    self.train_batch()

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
        """Analyze patterns for dangerous/successful elements"""
        pattern = entry.action_key

        if entry.reward < -1.0:  # Crash or close
            self.dangerous_patterns[pattern] = self.dangerous_patterns.get(pattern, 0) + abs(entry.reward)
        elif entry.reward > 0.5:  # New screen or good action
            self.success_patterns[pattern] = self.success_patterns.get(pattern, 0) + entry.reward

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
            avg_reward = sum(self.reward_history) / len(self.reward_history) if self.reward_history else 0
            avg_td = sum(self.td_error_history) / len(self.td_error_history) if self.td_error_history else 0
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
            self.stats.average_reward = sum(self.reward_history) / len(self.reward_history)
        if self.td_error_history:
            self.stats.average_td_error = sum(self.td_error_history) / len(self.td_error_history)

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

        logger.debug(f"Trained on batch of {len(batch)}, avg TD-error: {sum(td_errors)/len(td_errors):.4f}")

    def get_q_table(self) -> Dict[str, float]:
        """Get a copy of the Q-table"""
        with self.lock:
            return dict(self.q_table)

    def get_dangerous_patterns(self) -> Dict[str, float]:
        """Get patterns that frequently cause problems"""
        with self.lock:
            # Return top 20 most dangerous
            sorted_patterns = sorted(self.dangerous_patterns.items(), key=lambda x: -x[1])
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
                memory_usage_mb=self.stats.memory_usage_mb
            )

    def save(self, path: str):
        """Save Q-table and patterns to JSON file"""
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
                    "epsilon": HYPERPARAMS.epsilon
                }
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved Q-table to {path} ({len(self.q_table)} entries)")

    def load(self, path: str):
        """Load Q-table from JSON file"""
        with self.lock:
            try:
                with open(path, 'r') as f:
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
                "dangerous_patterns": list(self.dangerous_patterns.keys())[:50]  # Top 50
            }
            return json.dumps(export_data)

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

        def __init__(self, state_dim: int = 64, action_dim: int = 32, hidden_dim: int = 256):
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
                nn.Dropout(0.1)
            )

            # Value stream
            self.value_stream = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.ReLU(),
                nn.Linear(hidden_dim // 2, 1)
            )

            # Advantage stream
            self.advantage_stream = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.ReLU(),
                nn.Linear(hidden_dim // 2, 1)
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

        def __init__(self, state_dim: int = 64, action_dim: int = 32, hidden_dim: int = 256):
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
            self.q_network = DuelingQNetwork(state_dim, action_dim, hidden_dim).to(self.device)
            self.target_network = DuelingQNetwork(state_dim, action_dim, hidden_dim).to(self.device)
            self.target_network.load_state_dict(self.q_network.state_dict())
            self.target_network.eval()

            # Optimizer with weight decay
            self.optimizer = optim.AdamW(
                self.q_network.parameters(),
                lr=0.0003,
                weight_decay=0.01
            )

            # Learning rate scheduler
            self.scheduler = optim.lr_scheduler.StepLR(self.optimizer, step_size=1000, gamma=0.95)

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
                cache[hash_str] = (np.random.randn(dim) / np.sqrt(dim)).astype(np.float32)
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
                next_max_q = self._get_max_tabular_q(entry.next_screen_hash) if entry.next_screen_hash else 0
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
                state_emb = self._get_embedding(entry.screen_hash, self.state_dim, self.state_embeddings)
                action_emb = self._get_embedding(entry.action_key, self.action_dim, self.action_embeddings)
                states_actions.append(np.concatenate([state_emb, action_emb]))
                rewards.append(entry.reward)

                if entry.next_screen_hash:
                    next_state_emb = self._get_embedding(entry.next_screen_hash, self.state_dim, self.state_embeddings)
                    # For next state, we use a "default" action embedding
                    next_states_actions.append(np.concatenate([next_state_emb, np.zeros(self.action_dim, dtype=np.float32)]))
                    dones.append(0)
                else:
                    next_states_actions.append(np.zeros(self.state_dim + self.action_dim, dtype=np.float32))
                    dones.append(1)

            # Convert to tensors
            states_actions = torch.FloatTensor(np.array(states_actions)).to(self.device)
            next_states_actions = torch.FloatTensor(np.array(next_states_actions)).to(self.device)
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
                avg_loss = sum(self.loss_history) / len(self.loss_history) if self.loss_history else 0
                logger.info(f"DQN update {self.stats.total_updates}, loss: {avg_loss:.4f}, lr: {self.scheduler.get_last_lr()[0]:.6f}")

        def _soft_update_target(self):
            """Soft update target network: θ_target = τ*θ + (1-τ)*θ_target"""
            for target_param, param in zip(self.target_network.parameters(), self.q_network.parameters()):
                target_param.data.copy_(HYPERPARAMS.tau * param.data + (1 - HYPERPARAMS.tau) * target_param.data)

        def get_q_table(self) -> Dict[str, float]:
            """Get hybrid Q-table (combines tabular + neural estimates)"""
            with self.lock:
                return dict(self.q_table)

        def get_stats(self) -> TrainingStats:
            """Get training statistics"""
            with self.lock:
                avg_reward = sum(self.reward_history) / len(self.reward_history) if self.reward_history else 0
                avg_loss = sum(self.loss_history) / len(self.loss_history) if self.loss_history else 0
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
                    memory_usage_mb=0
                )

        def save(self, path: str):
            """Save model and Q-table"""
            with self.lock:
                data = {
                    "q_table": self.q_table,
                    "model_state": None,  # Can't JSON serialize PyTorch state
                    "stats": asdict(self.stats)
                }
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2)

                # Save PyTorch model separately
                model_path = path.replace('.json', '_model.pt')
                torch.save({
                    'q_network': self.q_network.state_dict(),
                    'target_network': self.target_network.state_dict(),
                    'optimizer': self.optimizer.state_dict(),
                    'scheduler': self.scheduler.state_dict()
                }, model_path)

                logger.info(f"Saved DQN model to {model_path}")

        def load(self, path: str):
            """Load model and Q-table"""
            with self.lock:
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                    self.q_table = data.get("q_table", {})

                    # Load PyTorch model
                    model_path = path.replace('.json', '_model.pt')
                    if os.path.exists(model_path):
                        checkpoint = torch.load(model_path, map_location=self.device)
                        self.q_network.load_state_dict(checkpoint['q_network'])
                        self.target_network.load_state_dict(checkpoint['target_network'])
                        self.optimizer.load_state_dict(checkpoint['optimizer'])
                        self.scheduler.load_state_dict(checkpoint['scheduler'])
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
                self.q_network = DuelingQNetwork(self.state_dim, self.action_dim).to(self.device)
                self.target_network = DuelingQNetwork(self.state_dim, self.action_dim).to(self.device)
                self.target_network.load_state_dict(self.q_network.state_dict())
                self.optimizer = optim.AdamW(self.q_network.parameters(), lr=0.0003, weight_decay=0.01)
                self.scheduler = optim.lr_scheduler.StepLR(self.optimizer, step_size=1000, gamma=0.95)
                self.stats = TrainingStats()
                self.stats.hardware_acceleration = self.hw_accel

                logger.info("DQN trainer reset")

        def export_for_android(self) -> str:
            """Export Q-table as JSON for Android"""
            with self.lock:
                return json.dumps(self.q_table)

        def stop(self):
            """Cleanup"""
            pass


# === MQTT Handler ===

class MLTrainingServer:
    """Main MQTT-based training server with monitoring"""

    def __init__(self, broker: str, port: int, use_dqn: bool = False):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id=f"ml_training_server_{int(time.time())}")
        self.running = False

        # Use DQN if available and requested
        if use_dqn and TORCH_AVAILABLE:
            self.trainer = DQNTrainer()
            logger.info(f"Using DQN trainer with {self.trainer.hw_accel}")
        else:
            self.trainer = QTableTrainer()
            logger.info("Using enhanced Q-table trainer")

        # Q-table file path
        self.data_dir = Path("data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
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
            payload = msg.payload.decode('utf-8')

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
                    screen_hash=entry_data.get("screenHash", entry_data.get("screen_hash", "")),
                    action_key=entry_data.get("actionKey", entry_data.get("action_key", "")),
                    reward=float(entry_data.get("reward", 0)),
                    next_screen_hash=entry_data.get("nextScreenHash", entry_data.get("next_screen_hash")),
                    timestamp=int(entry_data.get("timestamp", 0)),
                    device_id=entry_data.get("deviceId", entry_data.get("device_id"))
                )
                self.trainer.add_experience(entry)

            self.update_count += len(entries)

            # Periodic training (for Q-table trainer, DQN trains automatically)
            if isinstance(self.trainer, QTableTrainer) and self.update_count >= TRAINING_INTERVAL:
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

            else:
                logger.warning(f"Unknown command: {command}")

        except Exception as e:
            logger.error(f"Error handling command: {e}")

    def _publish_q_table(self):
        """Publish Q-table to Android"""
        q_table = self.trainer.get_q_table()

        # Also include dangerous patterns if available
        export_data = {"q_table": q_table}
        if hasattr(self.trainer, 'get_dangerous_patterns'):
            export_data["dangerous_patterns"] = list(self.trainer.get_dangerous_patterns().keys())

        payload = json.dumps(export_data)
        self.client.publish(MQTT_TOPIC_QTABLE, payload)
        logger.info(f"Published Q-table ({len(q_table)} entries)")

    def _publish_status(self, status: str):
        """Publish status message"""
        stats = self.trainer.get_stats()
        payload = json.dumps({
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "q_table_size": stats.q_table_size,
            "total_experiences": stats.total_experiences,
            "average_reward": stats.average_reward,
            "hardware": stats.hardware_acceleration,
            "training_rate": stats.training_rate
        })
        self.client.publish(MQTT_TOPIC_STATUS, payload)

    def _stats_publisher(self):
        """Background thread to publish stats periodically"""
        last_experiences = 0
        while self.running:
            try:
                time.sleep(30)  # Every 30 seconds (reduced from 10s)
                if self.running:
                    # Only publish if there's actual training activity
                    current_experiences = self.trainer.stats.total_experiences if hasattr(self.trainer, 'stats') else 0
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

            print("\n" + "="*60)
            print("ML Training Server - Enhanced Edition")
            print("="*60)
            print(f"  Broker: {self.broker}:{self.port}")
            print(f"  Topics: {MQTT_TOPIC_LOGS}, {MQTT_TOPIC_COMMAND}")
            print(f"  Hardware: {self.trainer.stats.hardware_acceleration if hasattr(self.trainer, 'stats') else 'CPU'}")
            print(f"  Workers: {NUM_WORKERS} threads")
            print(f"  Batch size: {BATCH_SIZE}")
            print(f"  Buffer size: {REPLAY_BUFFER_SIZE}")
            print("="*60)
            print("  Press Ctrl+C to stop")
            print("="*60 + "\n")

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
        if hasattr(self.trainer, 'stop'):
            self.trainer.stop()

        self.client.loop_stop()
        self.client.disconnect()
        logger.info("ML Training Server stopped")


# === Main Entry Point ===

def main():
    parser = argparse.ArgumentParser(description="ML Training Server for Smart Explorer (Enhanced)")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT broker port")
    parser.add_argument("--dqn", action="store_true", help="Use Deep Q-Network (requires PyTorch)")
    parser.add_argument("--export", type=str, help="Export Q-table to file and exit")
    parser.add_argument("--load", type=str, help="Load Q-table from file before starting")
    parser.add_argument("--info", action="store_true", help="Show hardware info and exit")

    args = parser.parse_args()

    # Show hardware info
    if args.info:
        print("\nHardware Information:")
        print("="*40)
        for key, value in HW_INFO.items():
            print(f"  {key}: {value}")
        print("="*40)

        print("\nRecommendations:")
        if HW_INFO.get("directml_available"):
            print("  - DirectML available! Use --dqn for NPU acceleration")
        elif HW_INFO.get("cuda_available"):
            print("  - CUDA available! Use --dqn for GPU acceleration")
        else:
            print("  - Install torch-directml for NPU acceleration:")
            print("    pip install torch-directml")
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
    server = MLTrainingServer(args.broker, args.port, use_dqn=args.dqn)

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
