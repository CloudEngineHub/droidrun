"""Compatibility shim for the stealth device driver.

The implementation lives in ``mobilerun-core-local`` so local drivers are
owned by one package. This module preserves the historical
``mobilerun.tools.driver.stealth`` import path used by the framework, CLI,
and docs.
"""

from mobilerun_core_local.driver.stealth import StealthDriver, generate_curved_path

__all__ = ["StealthDriver", "generate_curved_path"]
