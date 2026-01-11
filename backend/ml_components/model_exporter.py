#!/usr/bin/env python3
"""
Model Exporter for Visual Mapper Smart Explorer

Converts Q-table data to TFLite neural network model for Android inference.
The model learns to approximate Q-values for state-action pairs.

Architecture:
- Input: 24 features (16 state + 8 action)
- Hidden: 64 → 32 neurons (ReLU)
- Output: 1 (Q-value prediction)

Usage:
    python model_exporter.py --input data/exploration_q_table.json --output models/q_network.tflite
    python model_exporter.py --bootstrap  # Create bootstrap model from BYD data
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

from services.feature_manager import get_feature_manager

# Check for required packages
feature_manager = get_feature_manager()
try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    logger.error("NumPy is required. Install with: pip install numpy")

TF_AVAILABLE = False
if feature_manager.is_enabled("ml_enabled"):
    try:
        import tensorflow as tf

        TF_AVAILABLE = True
        logger.info(f"TensorFlow version: {tf.__version__}")
    except ImportError:
        TF_AVAILABLE = False
        logger.warning("TensorFlow not available. Install with: pip install tensorflow")
else:
    logger.info("TensorFlow disabled by feature flag")


# === Feature Engineering ===


def hash_to_features(hash_str: str, dim: int = 16) -> np.ndarray:
    """
    Convert a hash string to a fixed-size feature vector.
    Uses deterministic pseudo-random encoding based on hash.
    """
    features = np.zeros(dim, dtype=np.float32)
    hash_val = hash(hash_str)

    for i in range(dim):
        # Create pseudo-random values from hash
        features[i] = np.sin(hash_val * (i + 1) * 0.1) * 0.5 + 0.5

    return features


def encode_state_action(screen_hash: str, action_key: str) -> np.ndarray:
    """
    Encode a state-action pair into a 24-dimensional feature vector.

    State features (16D): Hash-based encoding of screen
    Action features (8D): Hash-based encoding of action
    """
    state_features = hash_to_features(screen_hash, dim=16)
    action_features = hash_to_features(action_key, dim=8)
    return np.concatenate([state_features, action_features])


def prepare_training_data(q_table: Dict[str, float]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert Q-table to training data for neural network.

    Args:
        q_table: Dictionary of "screenHash|actionKey" -> Q-value

    Returns:
        X: Feature matrix (N x 24)
        y: Q-values (N,)
    """
    X_list = []
    y_list = []

    for key, q_value in q_table.items():
        if "|" not in key:
            continue

        parts = key.split("|", 1)
        if len(parts) != 2:
            continue

        screen_hash, action_key = parts
        features = encode_state_action(screen_hash, action_key)
        X_list.append(features)
        y_list.append(q_value)

    if not X_list:
        raise ValueError("No valid Q-table entries found")

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)

    logger.info(f"Prepared {len(X)} training samples from Q-table")
    return X, y


# === Neural Network Model (TensorFlow-dependent) ===

if TF_AVAILABLE:

    def create_q_network(input_dim: int = 24):
        """
        Create a simple neural network for Q-value prediction.

        Architecture matches Android TFLiteQNetwork expectations:
        - Input: 24 features
        - Hidden 1: 64 neurons, ReLU
        - Hidden 2: 32 neurons, ReLU
        - Output: 1 (Q-value)
        """
        model = tf.keras.Sequential(
            [
                tf.keras.layers.Input(shape=(input_dim,)),
                tf.keras.layers.Dense(64, activation="relu", name="dense1"),
                tf.keras.layers.BatchNormalization(),
                tf.keras.layers.Dense(32, activation="relu", name="dense2"),
                tf.keras.layers.BatchNormalization(),
                tf.keras.layers.Dense(1, name="output"),
            ]
        )

        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            loss="mse",
            metrics=["mae"],
        )

        return model

    def train_model(
        model,
        X: np.ndarray,
        y: np.ndarray,
        epochs: int = 100,
        batch_size: int = 32,
        validation_split: float = 0.2,
    ):
        """Train the Q-network on Q-table data."""

        callbacks = [
            tf.keras.callbacks.EarlyStopping(
                monitor="val_loss", patience=10, restore_best_weights=True
            ),
            tf.keras.callbacks.ReduceLROnPlateau(
                monitor="val_loss", factor=0.5, patience=5, min_lr=1e-6
            ),
        ]

        history = model.fit(
            X,
            y,
            epochs=epochs,
            batch_size=batch_size,
            validation_split=validation_split,
            callbacks=callbacks,
            verbose=1,
        )

        return history

    def export_to_tflite(model, output_path: str, quantize: bool = True) -> bytes:
        """
        Export Keras model to TFLite format.

        Args:
            model: Trained Keras model
            output_path: Path to save TFLite file
            quantize: Whether to apply float16 quantization (recommended for mobile)

        Returns:
            TFLite model bytes
        """
        converter = tf.lite.TFLiteConverter.from_keras_model(model)

        if quantize:
            # Float16 quantization: good balance of size and accuracy
            converter.optimizations = [tf.lite.Optimize.DEFAULT]
            converter.target_spec.supported_types = [tf.float16]

        tflite_model = converter.convert()

        # Save to file
        with open(output_path, "wb") as f:
            f.write(tflite_model)

        logger.info(
            f"Exported TFLite model: {output_path} ({len(tflite_model):,} bytes)"
        )
        return tflite_model


# === Q-Table Loading ===


def load_q_table(path: str) -> Dict[str, float]:
    """Load Q-table from JSON file (matches ml_training_server.py format)."""
    with open(path, "r") as f:
        data = json.load(f)

    # Handle both direct Q-table and wrapped format
    if "q_table" in data:
        q_table = data["q_table"]
    else:
        q_table = data

    logger.info(f"Loaded Q-table with {len(q_table)} entries from {path}")
    return q_table


def create_bootstrap_q_table() -> Dict[str, float]:
    """
    Create a bootstrap Q-table with common UI patterns.

    These patterns are generic enough to work with most Android apps
    and give the exploration a better starting point than random.
    """
    bootstrap = {}

    # Common positive patterns (elements that usually lead to new screens)
    positive_patterns = [
        # Navigation elements
        ("nav|menu|top", 0.8),
        ("nav|menu|bottom", 0.8),
        ("nav|drawer|top", 0.9),
        ("nav|home|bottom", 0.7),
        ("nav|settings|bottom", 0.7),
        # Buttons that lead to screens
        ("Button|enter|center", 0.6),
        ("Button|next|center", 0.7),
        ("Button|continue|center", 0.7),
        ("Button|more|bottom", 0.5),
        ("Button|details|center", 0.6),
        # List items (usually expandable)
        ("RecyclerView|item*|top", 0.5),
        ("RecyclerView|item*|center", 0.5),
        ("ListView|row*|center", 0.5),
        # Tab layouts
        ("TabLayout|tab*|top", 0.6),
        ("BottomNavigation|*|bottom", 0.7),
        # Cards and tiles
        ("CardView|card*|center", 0.5),
        ("MaterialCardView|*|center", 0.5),
    ]

    # Common negative patterns (elements that close/crash app or do nothing)
    negative_patterns = [
        # Close/cancel/back buttons
        ("Button|cancel|bottom", -0.3),
        ("Button|close|top", -0.5),
        ("ImageButton|back|top", -0.2),
        ("ImageButton|close|top", -0.5),
        # Dangerous patterns
        ("Button|logout|*", -1.0),
        ("Button|exit|*", -1.0),
        ("Button|delete|*", -0.8),
        ("Button|sign_out|*", -1.0),
        # Usually uninteresting elements
        ("TextView|*|center", -0.05),
        ("ImageView|*|center", -0.1),
    ]

    # Generate Q-table entries for different screen contexts
    screen_prefixes = ["main_", "home_", "list_", "detail_", "settings_"]

    for screen_prefix in screen_prefixes:
        # Screen hash would be computed, but we use prefixes for generalization
        for action_pattern, reward in positive_patterns:
            key = f"{screen_prefix}screen|{action_pattern}"
            bootstrap[key] = reward

        for action_pattern, reward in negative_patterns:
            key = f"{screen_prefix}screen|{action_pattern}"
            bootstrap[key] = reward

    logger.info(f"Created bootstrap Q-table with {len(bootstrap)} entries")
    return bootstrap


# === Main Export Pipeline ===


def export_q_table_to_tflite(
    input_path: str, output_path: str, epochs: int = 100
) -> Optional[str]:
    """
    Full pipeline: Load Q-table → Train NN → Export TFLite

    Args:
        input_path: Path to Q-table JSON file
        output_path: Path to save TFLite model
        epochs: Training epochs

    Returns:
        Output path on success, None on failure
    """
    if not TF_AVAILABLE:
        logger.error("TensorFlow is required for TFLite export")
        return None

    if not NUMPY_AVAILABLE:
        logger.error("NumPy is required for training")
        return None

    try:
        # Load Q-table
        q_table = load_q_table(input_path)

        if len(q_table) < 10:
            logger.warning(
                f"Q-table only has {len(q_table)} entries - model may not generalize well"
            )

        # Prepare training data
        X, y = prepare_training_data(q_table)

        # Normalize Q-values for training stability
        y_mean = np.mean(y)
        y_std = np.std(y) + 1e-8
        y_normalized = (y - y_mean) / y_std

        # Create and train model
        model = create_q_network(input_dim=24)
        model.summary()

        logger.info(f"Training on {len(X)} samples for {epochs} epochs...")
        history = train_model(model, X, y_normalized, epochs=epochs)

        # Report training results
        final_loss = history.history["loss"][-1]
        final_val_loss = history.history.get("val_loss", [final_loss])[-1]
        logger.info(
            f"Training complete: loss={final_loss:.4f}, val_loss={final_val_loss:.4f}"
        )

        # Export to TFLite
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        export_to_tflite(model, output_path, quantize=True)

        # Also save normalization params for inference
        norm_path = output_path.replace(".tflite", "_norm.json")
        with open(norm_path, "w") as f:
            json.dump({"mean": float(y_mean), "std": float(y_std)}, f)
        logger.info(f"Saved normalization params: {norm_path}")

        return output_path

    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        return None


def create_bootstrap_model(output_path: str) -> Optional[str]:
    """Create a bootstrap TFLite model from common UI patterns."""
    if not TF_AVAILABLE:
        logger.error("TensorFlow is required for TFLite export")
        return None

    try:
        # Create bootstrap Q-table
        q_table = create_bootstrap_q_table()

        # Save bootstrap Q-table for reference
        bootstrap_json = output_path.replace(".tflite", "_qtable.json")
        with open(bootstrap_json, "w") as f:
            json.dump({"q_table": q_table}, f, indent=2)
        logger.info(f"Saved bootstrap Q-table: {bootstrap_json}")

        # Prepare training data
        X, y = prepare_training_data(q_table)

        # Create and train model
        model = create_q_network(input_dim=24)

        # Train longer for bootstrap (we want it to generalize well)
        history = train_model(model, X, y, epochs=200, validation_split=0.1)

        # Export
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        export_to_tflite(model, output_path, quantize=True)

        logger.info(f"Bootstrap model created: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Bootstrap model creation failed: {e}", exc_info=True)
        return None


# === CLI ===


def main():
    parser = argparse.ArgumentParser(
        description="Export Q-table to TFLite model for Android inference"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default="data/exploration_q_table.json",
        help="Input Q-table JSON file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="models/q_network.tflite",
        help="Output TFLite model file",
    )
    parser.add_argument("--epochs", "-e", type=int, default=100, help="Training epochs")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create bootstrap model from common UI patterns",
    )
    parser.add_argument(
        "--android-assets",
        action="store_true",
        help="Also copy model to Android assets folder",
    )

    args = parser.parse_args()

    if args.bootstrap:
        output = create_bootstrap_model(args.output)
    else:
        if not os.path.exists(args.input):
            logger.error(f"Input file not found: {args.input}")
            logger.info("Use --bootstrap to create a bootstrap model instead")
            sys.exit(1)
        output = export_q_table_to_tflite(args.input, args.output, args.epochs)

    if output is None:
        logger.error("Export failed")
        sys.exit(1)

    # Copy to Android assets if requested
    if args.android_assets:
        android_assets_path = "android-companion/app/src/main/assets/models"
        os.makedirs(android_assets_path, exist_ok=True)

        import shutil

        dest = os.path.join(android_assets_path, os.path.basename(output))
        shutil.copy(output, dest)
        logger.info(f"Copied to Android assets: {dest}")

        # Also copy normalization params if they exist
        norm_path = output.replace(".tflite", "_norm.json")
        if os.path.exists(norm_path):
            shutil.copy(
                norm_path,
                os.path.join(android_assets_path, os.path.basename(norm_path)),
            )

    logger.info("Export complete!")


if __name__ == "__main__":
    main()
