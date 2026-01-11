"""
Visual Mapper - Navigation Manager
Core manager for app navigation graphs

Handles:
- CRUD operations for navigation graphs
- Screen identification and matching
- Pathfinding (Dijkstra's algorithm)
- Learning from recordings and mining
"""

import os
import json
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import heapq

from ml_components.navigation_models import (
    NavigationGraph,
    ScreenNode,
    ScreenTransition,
    TransitionAction,
    NavigationPath,
    LearnTransitionRequest,
    compute_screen_id,
    extract_ui_landmarks,
    generate_transition_id,
)

logger = logging.getLogger(__name__)


class NavigationManager:
    """
    Manages navigation graphs for Android apps

    Each app has one navigation graph stored in config/navigation/{package_hash}.json
    The graph learns screen transitions through recording, teaching, and mining.
    """

    def __init__(self, config_dir: str = "config/navigation"):
        """
        Initialize NavigationManager

        Args:
            config_dir: Directory to store navigation graph files
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of loaded graphs
        self._graph_cache: Dict[str, NavigationGraph] = {}

        logger.info(f"[NavigationManager] Initialized with config_dir: {self.config_dir}")

    # =========================================================================
    # File Operations
    # =========================================================================

    def _get_graph_path(self, package: str) -> Path:
        """Get file path for a package's navigation graph"""
        # Use hash to handle packages with special characters
        package_hash = hashlib.sha256(package.encode()).hexdigest()[:16]
        return self.config_dir / f"nav_{package_hash}.json"

    def _load_graph_from_file(self, package: str) -> Optional[NavigationGraph]:
        """Load navigation graph from disk"""
        path = self._get_graph_path(package)
        if not path.exists():
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            graph = NavigationGraph(**data)
            logger.debug(f"[NavigationManager] Loaded graph for {package} from {path}")
            return graph
        except Exception as e:
            logger.error(f"[NavigationManager] Failed to load graph for {package}: {e}")
            return None

    def _save_graph_to_file(self, graph: NavigationGraph) -> bool:
        """Save navigation graph to disk"""
        path = self._get_graph_path(graph.package)
        try:
            # Update timestamp
            graph.updated_at = datetime.now()

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(graph.model_dump(mode='json'), f, indent=2, default=str)

            logger.debug(f"[NavigationManager] Saved graph for {graph.package} to {path}")
            return True
        except Exception as e:
            logger.error(f"[NavigationManager] Failed to save graph for {graph.package}: {e}")
            return False

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def get_graph(self, package: str) -> Optional[NavigationGraph]:
        """
        Get navigation graph for a package

        Args:
            package: App package name

        Returns:
            NavigationGraph or None if not found
        """
        # Check cache first
        if package in self._graph_cache:
            return self._graph_cache[package]

        # Load from disk
        graph = self._load_graph_from_file(package)
        if graph:
            self._graph_cache[package] = graph

        return graph

    def get_or_create_graph(self, package: str, device_id: str = None) -> NavigationGraph:
        """
        Get existing graph or create a new one

        Args:
            package: App package name
            device_id: Optional device ID

        Returns:
            NavigationGraph (existing or new)
        """
        graph = self.get_graph(package)
        if graph:
            return graph

        # Create new graph
        graph = NavigationGraph(
            graph_id=hashlib.sha256(f"{package}_{datetime.now().isoformat()}".encode()).hexdigest()[:16],
            package=package,
            device_id=device_id,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        self._graph_cache[package] = graph
        self._save_graph_to_file(graph)

        logger.info(f"[NavigationManager] Created new graph for {package}")
        return graph

    def save_graph(self, graph: NavigationGraph) -> bool:
        """
        Save navigation graph

        Args:
            graph: NavigationGraph to save

        Returns:
            True if successful
        """
        self._graph_cache[graph.package] = graph
        return self._save_graph_to_file(graph)

    def delete_graph(self, package: str) -> bool:
        """
        Delete navigation graph

        Args:
            package: App package name

        Returns:
            True if successful
        """
        # Remove from cache
        if package in self._graph_cache:
            del self._graph_cache[package]

        # Delete file
        path = self._get_graph_path(package)
        if path.exists():
            try:
                path.unlink()
                logger.info(f"[NavigationManager] Deleted graph for {package}")
                return True
            except Exception as e:
                logger.error(f"[NavigationManager] Failed to delete graph for {package}: {e}")
                return False

        return True

    def list_graphs(self) -> List[str]:
        """
        List all packages with navigation graphs

        Returns:
            List of package names
        """
        packages = []
        for path in self.config_dir.glob("nav_*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                packages.append(data.get('package', 'unknown'))
            except Exception:
                pass
        return packages

    # =========================================================================
    # Screen Management
    # =========================================================================

    def add_screen(
        self,
        package: str,
        activity: str,
        ui_elements: List[Dict] = None,
        display_name: str = None,
        learned_from: str = "recording",
        is_home_screen: bool = False
    ) -> ScreenNode:
        """
        Add or update a screen in the navigation graph

        Args:
            package: App package name
            activity: Activity name
            ui_elements: UI elements for landmark extraction
            display_name: Human-readable name
            learned_from: How screen was discovered
            is_home_screen: Is this the app's home screen?

        Returns:
            The created/updated ScreenNode
        """
        graph = self.get_or_create_graph(package)

        # Extract landmarks from UI elements
        landmarks = extract_ui_landmarks(ui_elements or [])

        # Compute screen ID
        screen_id = compute_screen_id(activity, landmarks)

        # Check if screen exists
        if screen_id in graph.screens:
            # Update existing screen
            screen = graph.screens[screen_id]
            screen.last_seen = datetime.now()
            screen.visit_count += 1
            if display_name:
                screen.display_name = display_name
            if is_home_screen:
                screen.is_home_screen = True
                graph.home_screen_id = screen_id
        else:
            # Create new screen
            screen = ScreenNode(
                screen_id=screen_id,
                package=package,
                activity=activity,
                display_name=display_name or activity.split('.')[-1],  # Use class name as default
                ui_landmarks=landmarks,
                learned_from=learned_from,
                is_home_screen=is_home_screen,
                visit_count=1
            )
            graph.screens[screen_id] = screen

            if is_home_screen:
                graph.home_screen_id = screen_id

            logger.info(f"[NavigationManager] Added screen: {screen.display_name} ({screen_id[:8]}...)")

        self.save_graph(graph)
        return screen

    def get_screen(self, package: str, screen_id: str) -> Optional[ScreenNode]:
        """Get a specific screen by ID"""
        graph = self.get_graph(package)
        if not graph:
            return None
        return graph.screens.get(screen_id)

    def identify_current_screen(
        self,
        package: str,
        activity: str,
        ui_elements: List[Dict] = None
    ) -> Optional[ScreenNode]:
        """
        Identify which known screen matches the current state

        Args:
            package: App package name
            activity: Current activity name
            ui_elements: Current UI elements

        Returns:
            Matching ScreenNode or None
        """
        graph = self.get_graph(package)
        if not graph:
            return None

        # Extract landmarks and compute ID
        landmarks = extract_ui_landmarks(ui_elements or [])
        screen_id = compute_screen_id(activity, landmarks)

        # Check for exact match
        if screen_id in graph.screens:
            return graph.screens[screen_id]

        # Try matching by activity alone (less precise)
        for screen in graph.screens.values():
            if screen.activity == activity:
                return screen

        return None

    # =========================================================================
    # Transition Management
    # =========================================================================

    def add_transition(
        self,
        package: str,
        source_screen_id: str,
        target_screen_id: str,
        action: TransitionAction,
        learned_from: str = "recording"
    ) -> Optional[ScreenTransition]:
        """
        Add or update a transition between screens

        Args:
            package: App package name
            source_screen_id: Source screen ID
            target_screen_id: Target screen ID
            action: The action that causes this transition
            learned_from: How transition was learned

        Returns:
            The created/updated ScreenTransition
        """
        graph = self.get_or_create_graph(package)

        # Generate transition ID
        transition_id = generate_transition_id(source_screen_id, target_screen_id, action)

        # Check if transition exists
        existing = None
        for t in graph.transitions:
            if t.transition_id == transition_id:
                existing = t
                break

        if existing:
            # Update existing transition
            existing.usage_count += 1
            existing.last_used = datetime.now()
            logger.debug(f"[NavigationManager] Updated transition: {transition_id[:8]}... (count: {existing.usage_count})")
        else:
            # Create new transition
            transition = ScreenTransition(
                transition_id=transition_id,
                source_screen_id=source_screen_id,
                target_screen_id=target_screen_id,
                action=action,
                learned_from=learned_from,
                usage_count=1
            )
            graph.transitions.append(transition)
            existing = transition
            logger.info(f"[NavigationManager] Added transition: {source_screen_id[:8]}... -> {target_screen_id[:8]}...")

        self.save_graph(graph)
        return existing

    def get_transitions_from(self, package: str, screen_id: str) -> List[ScreenTransition]:
        """Get all transitions FROM a screen"""
        graph = self.get_graph(package)
        if not graph:
            return []
        return [t for t in graph.transitions if t.source_screen_id == screen_id]

    def get_transitions_to(self, package: str, screen_id: str) -> List[ScreenTransition]:
        """Get all transitions TO a screen"""
        graph = self.get_graph(package)
        if not graph:
            return []
        return [t for t in graph.transitions if t.target_screen_id == screen_id]

    def update_transition_stats(
        self,
        package: str,
        transition_id: str,
        success: bool,
        time_ms: int = None
    ):
        """
        Update transition statistics after use

        Args:
            package: App package name
            transition_id: Transition ID
            success: Whether the transition succeeded
            time_ms: Time taken for transition
        """
        graph = self.get_graph(package)
        if not graph:
            return

        for t in graph.transitions:
            if t.transition_id == transition_id:
                t.usage_count += 1
                t.last_used = datetime.now()
                t.last_success = success

                # Update success rate (exponential moving average)
                alpha = 0.2  # Weight for new observation
                t.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * t.success_rate

                # Update average time
                if time_ms:
                    t.avg_transition_time_ms = int(
                        alpha * time_ms + (1 - alpha) * t.avg_transition_time_ms
                    )

                self.save_graph(graph)
                return

    # =========================================================================
    # Pathfinding (Dijkstra's Algorithm)
    # =========================================================================

    def find_path(
        self,
        package: str,
        from_screen_id: str,
        to_screen_id: str
    ) -> Optional[NavigationPath]:
        """
        Find the best path from one screen to another

        Uses Dijkstra's algorithm weighted by:
        - Success rate (higher = lower cost)
        - Average transition time (lower = lower cost)
        - Usage count (higher = lower cost, more proven)

        Args:
            package: App package name
            from_screen_id: Starting screen ID
            to_screen_id: Target screen ID

        Returns:
            NavigationPath or None if no path found
        """
        graph = self.get_graph(package)
        if not graph:
            logger.warning(f"[NavigationManager] No graph found for {package}")
            return None

        if from_screen_id == to_screen_id:
            # Already at target
            return NavigationPath(
                from_screen_id=from_screen_id,
                to_screen_id=to_screen_id,
                transitions=[],
                total_cost=0,
                estimated_time_ms=0
            )

        # Build adjacency list
        adjacency: Dict[str, List[Tuple[str, ScreenTransition, float]]] = {}
        for screen_id in graph.screens:
            adjacency[screen_id] = []

        for t in graph.transitions:
            if t.source_screen_id in adjacency:
                # Calculate edge cost (lower is better)
                cost = self._calculate_transition_cost(t)
                adjacency[t.source_screen_id].append((t.target_screen_id, t, cost))

        # Dijkstra's algorithm
        distances = {screen_id: float('inf') for screen_id in graph.screens}
        distances[from_screen_id] = 0
        predecessors: Dict[str, Tuple[str, ScreenTransition]] = {}

        # Priority queue: (distance, screen_id)
        pq = [(0, from_screen_id)]

        while pq:
            current_dist, current = heapq.heappop(pq)

            if current == to_screen_id:
                # Found path! Reconstruct it
                path_transitions = []
                node = to_screen_id
                while node in predecessors:
                    prev_node, transition = predecessors[node]
                    path_transitions.append(transition)
                    node = prev_node
                path_transitions.reverse()

                total_time = sum(t.avg_transition_time_ms for t in path_transitions)

                return NavigationPath(
                    from_screen_id=from_screen_id,
                    to_screen_id=to_screen_id,
                    transitions=path_transitions,
                    total_cost=current_dist,
                    estimated_time_ms=total_time
                )

            if current_dist > distances[current]:
                continue  # Already processed with better distance

            for neighbor, transition, cost in adjacency.get(current, []):
                distance = current_dist + cost
                if distance < distances[neighbor]:
                    distances[neighbor] = distance
                    predecessors[neighbor] = (current, transition)
                    heapq.heappush(pq, (distance, neighbor))

        logger.warning(f"[NavigationManager] No path found from {from_screen_id[:8]}... to {to_screen_id[:8]}...")
        return None

    def _calculate_transition_cost(self, transition: ScreenTransition) -> float:
        """
        Calculate cost for a transition (used in pathfinding)

        Lower cost = better path

        Factors:
        - Success rate: High success = low cost
        - Time: Fast transitions = low cost
        - Usage: Well-used = low cost (proven reliable)
        """
        # Base cost
        cost = 1.0

        # Success rate factor (0.5 to 2.0)
        # Low success rate = high cost
        success_factor = 2.0 - transition.success_rate
        cost *= success_factor

        # Time factor (normalize to 0.5-1.5)
        # Fast transitions < 500ms = bonus
        # Slow transitions > 2000ms = penalty
        time_factor = 0.5 + (transition.avg_transition_time_ms / 2000.0)
        time_factor = min(max(time_factor, 0.5), 1.5)
        cost *= time_factor

        # Usage factor (proven paths are cheaper)
        # More usage = lower cost
        usage_factor = 1.0 / (1.0 + transition.usage_count * 0.1)
        cost *= usage_factor

        return cost

    # =========================================================================
    # Learning Methods
    # =========================================================================

    def learn_from_transition(self, request: LearnTransitionRequest) -> bool:
        """
        Learn from an observed screen transition

        Called by flow recorder when a transition is detected.

        Args:
            request: LearnTransitionRequest with before/after state

        Returns:
            True if learning was successful
        """
        try:
            package = request.before_package

            # Add/update source screen
            source_screen = self.add_screen(
                package=package,
                activity=request.before_activity,
                ui_elements=request.before_ui_elements,
                learned_from="recording"
            )

            # Add/update target screen
            target_screen = self.add_screen(
                package=package,
                activity=request.after_activity,
                ui_elements=request.after_ui_elements,
                learned_from="recording"
            )

            # Add transition
            self.add_transition(
                package=package,
                source_screen_id=source_screen.screen_id,
                target_screen_id=target_screen.screen_id,
                action=request.action,
                learned_from="recording"
            )

            logger.info(
                f"[NavigationManager] Learned transition: "
                f"{source_screen.display_name} -> {target_screen.display_name}"
            )
            return True

        except Exception as e:
            logger.error(f"[NavigationManager] Failed to learn transition: {e}", exc_info=True)
            return False

    def set_home_screen(self, package: str, activity: str, ui_elements: List[Dict] = None):
        """
        Set the home screen for an app

        Args:
            package: App package name
            activity: Home screen activity
            ui_elements: UI elements for identification
        """
        graph = self.get_or_create_graph(package)

        # Clear old home screen flag from ALL screens first
        for existing_screen in graph.screens.values():
            if existing_screen.is_home_screen:
                existing_screen.is_home_screen = False
                logger.debug(f"[NavigationManager] Cleared home flag from: {existing_screen.display_name}")

        # Now add/update the new home screen
        screen = self.add_screen(
            package=package,
            activity=activity,
            ui_elements=ui_elements,
            learned_from="recording",
            is_home_screen=True
        )

        # Ensure graph home_screen_id is set
        graph.home_screen_id = screen.screen_id
        self.save_graph(graph)

        logger.info(f"[NavigationManager] Set home screen for {package}: {screen.display_name}")

    # =========================================================================
    # Statistics & Debugging
    # =========================================================================

    def get_graph_stats(self, package: str) -> Optional[Dict]:
        """Get statistics about a navigation graph"""
        graph = self.get_graph(package)
        if not graph:
            return None

        return {
            "package": graph.package,
            "screen_count": len(graph.screens),
            "transition_count": len(graph.transitions),
            "home_screen_id": graph.home_screen_id,
            "created_at": graph.created_at.isoformat() if graph.created_at else None,
            "updated_at": graph.updated_at.isoformat() if graph.updated_at else None,
            "total_recordings": graph.total_recordings,
            "total_navigations": graph.total_navigations
        }

    def export_graph_as_dot(self, package: str) -> Optional[str]:
        """
        Export navigation graph as DOT format for visualization

        Can be rendered with Graphviz or similar tools
        """
        graph = self.get_graph(package)
        if not graph:
            return None

        lines = ["digraph NavigationGraph {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=box];")

        # Add nodes
        for screen_id, screen in graph.screens.items():
            label = screen.display_name or screen.activity.split('.')[-1]
            style = "style=filled,fillcolor=lightgreen" if screen.is_home_screen else ""
            lines.append(f'  "{screen_id[:8]}" [label="{label}" {style}];')

        # Add edges
        for t in graph.transitions:
            label = t.action.action_type
            if t.action.description:
                label = t.action.description[:20]
            lines.append(
                f'  "{t.source_screen_id[:8]}" -> "{t.target_screen_id[:8]}" '
                f'[label="{label}" tooltip="success: {t.success_rate:.0%}"];'
            )

        lines.append("}")
        return "\n".join(lines)
