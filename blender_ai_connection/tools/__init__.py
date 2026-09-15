"""Tool package — imports every tool module so they self-register.

Add a new tool by creating a function in the matching ``*_tools.py`` module
(or a new module imported below) and decorating it with ``@register_tool``.
No other file needs to change.
"""

from .base import (  # noqa: F401  (re-exported public API)
    TOOL_CATEGORIES,
    TOOL_REGISTRY,
    ToolError,
    get_tool,
    list_tools,
    register_tool,
    require_bpy,
    tools_manifest,
    validate_params,
)

from . import scene_tools  # noqa: F401,E402
from . import modeling_tools  # noqa: F401,E402
from . import material_tools  # noqa: F401,E402
from . import animation_tools  # noqa: F401,E402
from . import camera_tools  # noqa: F401,E402
from . import lighting_tools  # noqa: F401,E402
from . import rendering_tools  # noqa: F401,E402
from . import nodes_tools  # noqa: F401,E402
from . import physics_tools  # noqa: F401,E402
from . import project_tools  # noqa: F401,E402
from . import character_tools  # noqa: F401,E402
from . import environment_tools  # noqa: F401,E402
from . import procedural_tools  # noqa: F401,E402
from . import optimization_tools  # noqa: F401,E402
from . import debug_tools  # noqa: F401,E402
from . import cutscene_tools  # noqa: F401,E402
