"""Compatibility shim for the recording device driver.

The implementation lives in ``mobilerun-core-local`` so local drivers are
owned by one package. This module preserves the historical
``mobilerun.tools.driver.recording`` import path used by the framework, CLI,
and docs.
"""

from mobilerun_core_local.driver.recording import RecordingDriver

__all__ = ["RecordingDriver"]
