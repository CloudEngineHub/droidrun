"""Compatibility shim for the visual remote device driver.

The implementation lives in ``mobilerun-core-local`` so local drivers are
owned by one package. This module preserves the historical
``mobilerun.tools.driver.visual_remote`` import path used by the framework,
CLI, and docs.
"""

from mobilerun_core_local.driver.visual_remote import (
    SCREENSHOT_COORDINATE_SPACE,
    VISUAL_REMOTE_CONNECTION,
    VISUAL_REMOTE_DEFAULT_URL,
    VisualRemoteDriver,
    validate_visual_remote_url,
)

__all__ = [
    "SCREENSHOT_COORDINATE_SPACE",
    "VISUAL_REMOTE_CONNECTION",
    "VISUAL_REMOTE_DEFAULT_URL",
    "VisualRemoteDriver",
    "validate_visual_remote_url",
]
