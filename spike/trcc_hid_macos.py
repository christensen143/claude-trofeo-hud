"""Spike: run the trcc CLI with the HID wire routed through hidapi on macOS.

trcc maps Wire.HID to a libusb bulk transport on every OS; macOS's HID kernel
driver owns the device, so libusb open fails with EACCES. The library ships an
unused HidApiTransport (IOHIDManager-backed) — patch it in for Wire.HID and
then run the normal CLI, e.g.:

    uv run python spike/trcc_hid_macos.py display color 0416:5302 ff0000
"""
import sys

from trcc.adapters.device.transport import HidApiTransport
from trcc.adapters.system import macos
from trcc.core.models import Wire

_orig = macos.MacOSPlatform._transport_openers


def _patched(self):
    openers = dict(_orig(self))
    openers[Wire.HID] = lambda vid, pid, serial=None: HidApiTransport(vid, pid, serial)
    return openers


macos.MacOSPlatform._transport_openers = _patched

from trcc._entry import main  # noqa: E402  (import after patch)

sys.exit(main())
