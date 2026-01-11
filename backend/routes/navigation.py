"""
Visual Mapper - Navigation API Routes
API endpoints for navigation graph learning and management
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

from ml_components.navigation_models import (
    NavigationGraph,
    ScreenNode,
    ScreenTransition,
    TransitionAction,
    LearnTransitionRequest,
    NavigationPath,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/navigation", tags=["Navigation"])


# ============================================================================
# Dependency Injection (set by routes/__init__.py)
# ============================================================================

_navigation_manager = None


def set_navigation_manager(manager):
    """Set the navigation manager instance (called from routes/__init__.py)"""
    global _navigation_manager
    _navigation_manager = manager


def get_navigation_manager():
    """Get the navigation manager instance"""
    if _navigation_manager is None:
        raise HTTPException(status_code=500, detail="NavigationManager not initialized")
    return _navigation_manager


# ============================================================================
# Request/Response Models
# ============================================================================


class AddScreenRequest(BaseModel):
    """Request to manually add a screen"""

    activity: str
    display_name: Optional[str] = None
    ui_elements: List[Dict[str, Any]] = []
    is_home_screen: bool = False


class AddTransitionRequest(BaseModel):
    """Request to manually add a transition"""

    source_screen_id: str
    target_screen_id: str
    action: TransitionAction


class MineFlowsRequest(BaseModel):
    """Request to mine navigation from existing flows"""

    device_id: Optional[str] = None
    limit: Optional[int] = None  # Max flows to mine


class GraphStatsResponse(BaseModel):
    """Navigation graph statistics"""

    package: str
    screen_count: int
    transition_count: int
    home_screen_id: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


# ============================================================================
# Graph CRUD Endpoints
# ============================================================================


@router.get("/{package}")
async def get_navigation_graph(package: str) -> Dict[str, Any]:
    """
    Get navigation graph for an app package

    Args:
        package: App package name (e.g., com.spotify.music)

    Returns:
        Navigation graph data or error
    """
    manager = get_navigation_manager()
    graph = manager.get_graph(package)

    if not graph:
        raise HTTPException(
            status_code=404, detail=f"No navigation graph found for {package}"
        )

    return {"success": True, "graph": graph.model_dump(mode="json")}


@router.get("/")
async def list_navigation_graphs() -> Dict[str, Any]:
    """
    List all packages with navigation graphs

    Returns:
        List of package names
    """
    manager = get_navigation_manager()
    packages = manager.list_graphs()

    return {"success": True, "packages": packages, "count": len(packages)}


@router.delete("/{package}")
async def delete_navigation_graph(package: str) -> Dict[str, Any]:
    """
    Delete navigation graph for an app

    Args:
        package: App package name

    Returns:
        Success status
    """
    manager = get_navigation_manager()
    success = manager.delete_graph(package)

    if not success:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete graph for {package}"
        )

    return {"success": True, "message": f"Deleted navigation graph for {package}"}


@router.get("/{package}/stats")
async def get_graph_stats(package: str, allow_missing: bool = False) -> Dict[str, Any]:
    """
    Get statistics about a navigation graph

    Args:
        package: App package name

    Returns:
        Graph statistics
    """
    manager = get_navigation_manager()
    stats = manager.get_graph_stats(package)

    if not stats:
        if allow_missing:
            return {
                "success": False,
                "stats": None,
                "message": f"No navigation graph found for {package}",
            }
        raise HTTPException(
            status_code=404, detail=f"No navigation graph found for {package}"
        )

    return {"success": True, "stats": stats}


# ============================================================================
# Screen Endpoints
# ============================================================================


@router.get("/{package}/screens")
async def list_screens(package: str) -> Dict[str, Any]:
    """
    List all known screens for an app

    Args:
        package: App package name

    Returns:
        List of screens
    """
    manager = get_navigation_manager()
    graph = manager.get_graph(package)

    if not graph:
        return {"success": True, "screens": [], "count": 0}

    screens = list(graph.screens.values())
    return {
        "success": True,
        "screens": [s.model_dump(mode="json") for s in screens],
        "count": len(screens),
    }


@router.post("/{package}/screens")
async def add_screen(package: str, request: AddScreenRequest) -> Dict[str, Any]:
    """
    Manually add a screen to the navigation graph

    Args:
        package: App package name
        request: Screen details

    Returns:
        Created screen
    """
    manager = get_navigation_manager()

    screen = manager.add_screen(
        package=package,
        activity=request.activity,
        ui_elements=request.ui_elements,
        display_name=request.display_name,
        learned_from="teaching",
        is_home_screen=request.is_home_screen,
    )

    return {"success": True, "screen": screen.model_dump(mode="json")}


@router.get("/{package}/screens/{screen_id}")
async def get_screen(package: str, screen_id: str) -> Dict[str, Any]:
    """
    Get a specific screen by ID

    Args:
        package: App package name
        screen_id: Screen ID

    Returns:
        Screen details
    """
    manager = get_navigation_manager()
    screen = manager.get_screen(package, screen_id)

    if not screen:
        raise HTTPException(status_code=404, detail=f"Screen {screen_id} not found")

    return {"success": True, "screen": screen.model_dump(mode="json")}


@router.put("/{package}/screens/{screen_id}")
async def update_screen(
    package: str,
    screen_id: str,
    display_name: Optional[str] = None,
    is_home_screen: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Update screen properties

    Args:
        package: App package name
        screen_id: Screen ID
        display_name: New display name
        is_home_screen: Set as home screen

    Returns:
        Updated screen
    """
    manager = get_navigation_manager()
    graph = manager.get_graph(package)

    if not graph or screen_id not in graph.screens:
        raise HTTPException(status_code=404, detail=f"Screen {screen_id} not found")

    screen = graph.screens[screen_id]

    if display_name is not None:
        screen.display_name = display_name

    if is_home_screen is not None:
        screen.is_home_screen = is_home_screen
        if is_home_screen:
            # Clear other home screens
            for s in graph.screens.values():
                if s.screen_id != screen_id:
                    s.is_home_screen = False
            graph.home_screen_id = screen_id

    manager.save_graph(graph)

    return {"success": True, "screen": screen.model_dump(mode="json")}


# ============================================================================
# Transition Endpoints
# ============================================================================


@router.get("/{package}/transitions")
async def list_transitions(package: str) -> Dict[str, Any]:
    """
    List all transitions for an app

    Args:
        package: App package name

    Returns:
        List of transitions
    """
    manager = get_navigation_manager()
    graph = manager.get_graph(package)

    if not graph:
        return {"success": True, "transitions": [], "count": 0}

    return {
        "success": True,
        "transitions": [t.model_dump(mode="json") for t in graph.transitions],
        "count": len(graph.transitions),
    }


@router.post("/{package}/transitions")
async def add_transition(package: str, request: AddTransitionRequest) -> Dict[str, Any]:
    """
    Manually add a transition between screens

    Args:
        package: App package name
        request: Transition details

    Returns:
        Created transition
    """
    manager = get_navigation_manager()

    transition = manager.add_transition(
        package=package,
        source_screen_id=request.source_screen_id,
        target_screen_id=request.target_screen_id,
        action=request.action,
        learned_from="teaching",
    )

    if not transition:
        raise HTTPException(status_code=500, detail="Failed to add transition")

    return {"success": True, "transition": transition.model_dump(mode="json")}


@router.delete("/{package}/transitions/{transition_id}")
async def delete_transition(package: str, transition_id: str) -> Dict[str, Any]:
    """
    Delete a transition

    Args:
        package: App package name
        transition_id: Transition ID

    Returns:
        Success status
    """
    manager = get_navigation_manager()
    graph = manager.get_graph(package)

    if not graph:
        raise HTTPException(status_code=404, detail=f"No graph found for {package}")

    # Find and remove transition
    original_count = len(graph.transitions)
    graph.transitions = [
        t for t in graph.transitions if t.transition_id != transition_id
    ]

    if len(graph.transitions) == original_count:
        raise HTTPException(
            status_code=404, detail=f"Transition {transition_id} not found"
        )

    manager.save_graph(graph)

    return {"success": True, "message": f"Deleted transition {transition_id}"}


# ============================================================================
# Learning Endpoints
# ============================================================================


@router.post("/{package}/learn-transition")
async def learn_transition(
    package: str, request: LearnTransitionRequest
) -> Dict[str, Any]:
    """
    Learn from an observed screen transition

    Called by flow recorder when a transition is detected.

    Args:
        package: App package name
        request: Before/after state and action

    Returns:
        Success status and learned data
    """
    manager = get_navigation_manager()

    # Ensure package matches
    if request.before_package != package:
        logger.warning(f"Package mismatch: {request.before_package} vs {package}")

    success = manager.learn_from_transition(request)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to learn transition")

    return {
        "success": True,
        "message": "Transition learned successfully",
        "from_activity": request.before_activity,
        "to_activity": request.after_activity,
    }


@router.post("/{package}/set-home-screen")
async def set_home_screen(
    package: str,
    activity: str = Query(..., description="Home screen activity name"),
    ui_elements: List[Dict[str, Any]] = Body(default=[]),
) -> Dict[str, Any]:
    """
    Set the home screen for an app

    Args:
        package: App package name
        activity: Home screen activity
        ui_elements: UI elements for identification

    Returns:
        Success status
    """
    manager = get_navigation_manager()
    manager.set_home_screen(package, activity, ui_elements)

    return {"success": True, "message": f"Set home screen for {package} to {activity}"}


# ============================================================================
# Pathfinding Endpoints
# ============================================================================


@router.get("/{package}/path")
async def find_path(
    package: str,
    from_screen: str = Query(..., description="Source screen ID"),
    to_screen: str = Query(..., description="Target screen ID"),
) -> Dict[str, Any]:
    """
    Find navigation path between two screens

    Uses Dijkstra's algorithm to find the best path.

    Args:
        package: App package name
        from_screen: Source screen ID
        to_screen: Target screen ID

    Returns:
        Navigation path or error
    """
    manager = get_navigation_manager()
    path = manager.find_path(package, from_screen, to_screen)

    if not path:
        raise HTTPException(
            status_code=404, detail=f"No path found from {from_screen} to {to_screen}"
        )

    return {
        "success": True,
        "path": {
            "from_screen_id": path.from_screen_id,
            "to_screen_id": path.to_screen_id,
            "hop_count": path.hop_count,
            "total_cost": path.total_cost,
            "estimated_time_ms": path.estimated_time_ms,
            "transitions": [t.model_dump(mode="json") for t in path.transitions],
        },
    }


# ============================================================================
# Mining Endpoints
# ============================================================================


@router.post("/{package}/mine")
async def mine_from_flows(
    package: str, request: MineFlowsRequest = None
) -> Dict[str, Any]:
    """
    Mine navigation patterns from existing flows

    Analyzes saved flows and extracts screen transitions.

    Args:
        package: App package name
        request: Mining options

    Returns:
        Mining results
    """
    # Import here to avoid circular imports
    from navigation_miner import NavigationMiner

    manager = get_navigation_manager()

    try:
        miner = NavigationMiner(manager)
        result = miner.mine_package(
            package=package,
            device_id=request.device_id if request else None,
            limit=request.limit if request else None,
        )

        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Mining failed for {package}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Mining failed: {str(e)}")


# ============================================================================
# Export/Visualization Endpoints
# ============================================================================


@router.get("/{package}/export/dot")
async def export_as_dot(package: str) -> Dict[str, Any]:
    """
    Export navigation graph as DOT format

    Can be rendered with Graphviz or similar tools.

    Args:
        package: App package name

    Returns:
        DOT format string
    """
    manager = get_navigation_manager()
    dot = manager.export_graph_as_dot(package)

    if not dot:
        raise HTTPException(status_code=404, detail=f"No graph found for {package}")

    return {"success": True, "format": "dot", "content": dot}
