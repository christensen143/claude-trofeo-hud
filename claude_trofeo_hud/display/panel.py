"""TrofeoPanel — drives the physical LCD via trcc's device classes.

macOS-specific path validated in spike/send_test_frame.py: trcc's own
platform layer routes HID through libusb (blocked by macOS), so we use
HidApiTransport (IOHIDManager) + HidLcd directly. Firmware 4.07 on this
panel blanks when idle, so callers must stream frames continuously.
"""
from __future__ import annotations

import io
import logging

from PIL import Image

log = logging.getLogger(__name__)

VID, PID = 0x0416, 0x5302
_BCD_FIRMWARE = 0x0407  # our unit; quirk row keys on this


class TrofeoPanel:
    def __init__(self) -> None:
        self._dev = None
        self._size: tuple[int, int] | None = None

    @property
    def size(self) -> tuple[int, int] | None:
        return self._size

    @property
    def connected(self) -> bool:
        return self._dev is not None

    def connect(self) -> tuple[int, int]:
        from trcc.adapters.device.hid_lcd import HidLcd
        from trcc.adapters.device.transport import HidApiTransport
        from trcc.core.models import quirks_for
        from trcc.core.registry import find_product

        info = find_product(VID, PID)
        if info is None:
            raise RuntimeError(f"{VID:04x}:{PID:04x} not in trcc registry")
        dev = HidLcd(info, HidApiTransport(VID, PID))
        dev.set_quirks(quirks_for(VID, PID, _BCD_FIRMWARE))
        result = dev.connect()
        self._dev = dev
        self._size = result.resolution
        log.info("panel connected: %sx%s PM=%s", *result.resolution,
                 result.pm_byte)
        return result.resolution

    def send(self, img: Image.Image) -> bool:
        if self._dev is None:
            raise RuntimeError("panel not connected")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=90)
        return bool(self._dev.send(buf.getvalue()))

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.disconnect()
            finally:
                self._dev = None
