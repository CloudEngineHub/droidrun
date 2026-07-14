"""Compat-shim tests for mobilerun.tools.driver.

The concrete driver implementations moved to mobilerun-core (CloudDriver) and
mobilerun-core-local (RecordingDriver, StealthDriver, VisualRemoteDriver).
mobilerun.tools.driver.* now re-exports those names to preserve historical
import paths. These tests assert the re-exports still work and resolve to
the exact same classes as the core packages.
"""

import unittest

import mobilerun_core.driver.cloud
import mobilerun_core_local.driver.recording
import mobilerun_core_local.driver.stealth
import mobilerun_core_local.driver.visual_remote

import mobilerun.tools
from mobilerun.tools.driver import (
    CloudDriver,
    RecordingDriver,
    StealthDriver,
    VisualRemoteDriver,
)
from mobilerun.tools.driver.cloud import CloudDriver as CloudDriverFromSubmodule
from mobilerun.tools.driver.recording import (
    RecordingDriver as RecordingDriverFromSubmodule,
)
from mobilerun.tools.driver.stealth import StealthDriver as StealthDriverFromSubmodule
from mobilerun.tools.driver.visual_remote import (
    VisualRemoteDriver as VisualRemoteDriverFromSubmodule,
)


class DriverReexportImportTest(unittest.TestCase):
    """Public names must be importable both from the package and each shim submodule."""

    def test_recording_driver_importable_from_submodule(self):
        self.assertIs(RecordingDriverFromSubmodule, RecordingDriver)

    def test_stealth_driver_importable_from_submodule(self):
        self.assertIs(StealthDriverFromSubmodule, StealthDriver)

    def test_visual_remote_driver_importable_from_submodule(self):
        self.assertIs(VisualRemoteDriverFromSubmodule, VisualRemoteDriver)

    def test_cloud_driver_importable_from_submodule(self):
        self.assertIs(CloudDriverFromSubmodule, CloudDriver)


class DriverReexportIdentityTest(unittest.TestCase):
    """Shim classes must be the exact same objects as the core implementations."""

    def test_recording_driver_is_core_local_implementation(self):
        self.assertIs(
            RecordingDriver,
            mobilerun_core_local.driver.recording.RecordingDriver,
        )

    def test_stealth_driver_is_core_local_implementation(self):
        self.assertIs(
            StealthDriver,
            mobilerun_core_local.driver.stealth.StealthDriver,
        )

    def test_visual_remote_driver_is_core_local_implementation(self):
        self.assertIs(
            VisualRemoteDriver,
            mobilerun_core_local.driver.visual_remote.VisualRemoteDriver,
        )

    def test_cloud_driver_is_core_implementation(self):
        self.assertIs(
            CloudDriver,
            mobilerun_core.driver.cloud.CloudDriver,
        )


class DriverReexportPackageLevelTest(unittest.TestCase):
    """mobilerun.tools re-exports a subset of driver names; verify those hold identity too."""

    def test_recording_driver_reexported_from_tools_package(self):
        # mobilerun/tools/__init__.py explicitly re-exports RecordingDriver.
        self.assertIs(mobilerun.tools.RecordingDriver, RecordingDriver)
        self.assertIs(
            mobilerun.tools.RecordingDriver,
            mobilerun_core_local.driver.recording.RecordingDriver,
        )

    def test_stealth_driver_not_reexported_from_tools_package(self):
        # mobilerun/tools/__init__.py does not re-export StealthDriver; only
        # mobilerun.tools.driver does. Documented here so this doesn't
        # silently regress if someone assumes otherwise.
        self.assertFalse(hasattr(mobilerun.tools, "StealthDriver"))

    def test_visual_remote_driver_not_reexported_from_tools_package(self):
        self.assertFalse(hasattr(mobilerun.tools, "VisualRemoteDriver"))

    def test_cloud_driver_not_reexported_from_tools_package(self):
        self.assertFalse(hasattr(mobilerun.tools, "CloudDriver"))


if __name__ == "__main__":
    unittest.main()
