"""Spike: drive the Trofeo Vision 6.86" (0416:5302) directly on macOS.

Bypasses trcc's CLI/App (whose macOS platform routes HID through libusb,
which macOS denies) and uses its device + transport classes directly:
HidApiTransport (IOHIDManager) + HidLcd (Type 2 protocol).

    uv run python spike/send_test_frame.py [seconds]
"""
import sys
import time

from PIL import Image, ImageDraw
from trcc.adapters.device.hid_lcd import HidLcd
from trcc.adapters.device.transport import HidApiTransport
from trcc.core.models import quirks_for
from trcc.core.registry import find_product

VID, PID, BCD = 0x0416, 0x5302, 0x0407


def build_test_image(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), "#1a1a2e")
    d = ImageDraw.Draw(img)
    # Corner markers to verify orientation and full-canvas coverage
    m = 40
    d.rectangle([0, 0, m, m], fill="#ff0000")            # top-left red
    d.rectangle([w - m, 0, w, m], fill="#00ff00")        # top-right green
    d.rectangle([0, h - m, m, h], fill="#0000ff")        # bottom-left blue
    d.rectangle([w - m, h - m, w, h], fill="#ffff00")    # bottom-right yellow
    d.rectangle([10, 10, w - 10, h - 10], outline="#D97757", width=4)
    d.text((w // 2, h // 2), f"CLAUDE HUD {w}x{h}", fill="#ffffff", anchor="mm", font_size=72)
    return img


def main() -> int:
    hold_s = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

    info = find_product(VID, PID)
    assert info is not None
    quirks = quirks_for(VID, PID, BCD)
    print(f"product={info.product} device_type={info.device_type} quirks={quirks}")

    transport = HidApiTransport(VID, PID)
    dev = HidLcd(info, transport)
    dev.set_quirks(quirks)

    result = dev.connect()
    print(f"handshake: PM={result.pm_byte} SUB={result.sub_byte} "
          f"resolution={result.resolution} raw={result.raw_response[:20].hex()}")
    profile = dev.profile
    print(f"profile: {profile}")

    w, h = profile.resolution if profile else result.resolution
    img = build_test_image(w, h)

    if profile and profile.jpeg:
        import io
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        payload = buf.getvalue()
        print(f"payload: JPEG {len(payload)} bytes")
    else:
        import numpy as np
        arr = np.asarray(img, dtype=np.uint16)
        rgb565 = ((arr[..., 0] >> 3) << 11) | ((arr[..., 1] >> 2) << 5) | (arr[..., 2] >> 3)
        order = profile.byte_order if profile else "<"
        payload = rgb565.astype(">u2" if order == ">" else "<u2").tobytes()
        print(f"payload: RGB565 {len(payload)} bytes (order {order})")

    # keepalive_stream firmware blanks when idle — stream the frame
    deadline = time.time() + hold_s
    frames = 0
    while time.time() < deadline:
        ok = dev.send(payload)
        frames += 1
        if not ok:
            print(f"send returned False on frame {frames}")
        time.sleep(0.2)
    print(f"sent {frames} frames over {hold_s}s")

    dev.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
