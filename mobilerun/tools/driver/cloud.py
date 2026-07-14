"""Compatibility shim for the cloud device driver.

The implementation lives in ``mobilerun-core`` so cloud-facing drivers are
owned by one package. This module preserves the historical
``mobilerun.tools.driver.cloud`` import path used by the framework, CLI, and docs.
"""

from mobilerun_core.driver.cloud import CloudDriver

__all__ = ["CloudDriver"]
