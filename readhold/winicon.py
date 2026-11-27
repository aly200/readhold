"""Put the Readhold logo on the desktop window (title bar and taskbar) on Windows.

pywebview only takes an icon on Linux; on Windows the window would show python's icon. Once the window
is shown we load assets/readhold.ico and hand it to the window with WM_SETICON. Any failure is logged
and ignored: a missing icon must never stop the app from opening.
"""
from __future__ import annotations

import ctypes
import logging
import sys

from . import config

log = logging.getLogger(__name__)

ICON = config.PROJECT_ROOT / "assets" / "readhold.ico"
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXSMICON, SM_CYSMICON, SM_CXICON, SM_CYICON = 49, 50, 11, 12


def _hwnd(window) -> int:
    native = getattr(window, "native", None)
    handle = getattr(native, "Handle", None)
    if handle is not None:
        try:
            return int(handle.ToInt64())
        except Exception:  # noqa: BLE001
            pass
    return ctypes.windll.user32.FindWindowW(None, window.title) or 0


def apply(window) -> None:
    if sys.platform != "win32" or not ICON.exists():
        return
    try:
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        hwnd = _hwnd(window)
        if not hwnd:
            log.warning("Window icon: window handle not found")
            return
        for which, cx, cy in ((ICON_SMALL, SM_CXSMICON, SM_CYSMICON), (ICON_BIG, SM_CXICON, SM_CYICON)):
            w, h = user32.GetSystemMetrics(cx), user32.GetSystemMetrics(cy)
            hicon = user32.LoadImageW(None, str(ICON), IMAGE_ICON, w, h, LR_LOADFROMFILE)
            if hicon:
                user32.SendMessageW(hwnd, WM_SETICON, which, hicon)
    except Exception:  # noqa: BLE001
        log.exception("Could not set the window icon")
