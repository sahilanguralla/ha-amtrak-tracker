"""Global fixtures for Amtrak Tracker integration tests."""

import threading
import pytest

# Store original threading.enumerate to prevent thread leak check failures
# caused by pycares DNS resolution shutdown loop threads in older HA test environments.
_original_enumerate = threading.enumerate


def patched_enumerate():
    """Patched version of threading.enumerate filtering out the safe shutdown loop thread."""
    return [t for t in _original_enumerate() if "_run_safe_shutdown_loop" not in t.name]


# Apply the patch immediately
threading.enumerate = patched_enumerate


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    yield
