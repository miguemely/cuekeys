# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""macOS-only window tweaks Qt doesn't expose, via the Objective-C runtime (ctypes).

Used to keep the overlay on every Space (desktop) and above full-screen apps.
"""

import ctypes
import ctypes.util
import logging
import sys

log = logging.getLogger(__name__)

# NSWindowCollectionBehavior flags
CAN_JOIN_ALL_SPACES = 1 << 0     # visible on every Space (Ctrl+Left/Right)
MOVE_TO_ACTIVE_SPACE = 1 << 1    # Qt sets this on tool windows; excludes CAN_JOIN_ALL_SPACES
MANAGED = 1 << 2                 # MANAGED / TRANSIENT / STATIONARY are mutually exclusive
TRANSIENT = 1 << 3
STATIONARY = 1 << 4              # stays put during Mission Control / Exposé
IGNORES_CYCLE = 1 << 6           # not part of Cmd+` window cycling
FULL_SCREEN_AUXILIARY = 1 << 8   # may appear next to full-screen apps

# NSWindowStyleMask: a non-activating panel is the only kind of window from a
# regular app that macOS lets into *another* app's full-screen Space.
NONACTIVATING_PANEL = 1 << 7

# NSWindowLevel: status-bar level floats above full-screen apps' windows.
STATUS_WINDOW_LEVEL = 25

ALL_SPACES_BEHAVIOR = CAN_JOIN_ALL_SPACES | STATIONARY | IGNORES_CYCLE | FULL_SCREEN_AUXILIARY
# AppKit throws (and kills the app) if these are combined with ALL_SPACES_BEHAVIOR.
CONFLICTING = MOVE_TO_ACTIVE_SPACE | MANAGED | TRANSIENT

_objc = None


def _runtime():
    global _objc
    if _objc is None:
        _objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.objc_getClass.argtypes = [ctypes.c_char_p]
    return _objc


def _is_panel(window):
    panel_class = _runtime().objc_getClass(b"NSPanel")
    return bool(_send(window, "isKindOfClass:", ctypes.c_bool, (ctypes.c_void_p,), panel_class))


def _send(receiver, selector, restype=ctypes.c_void_p, argtypes=(), *args):
    # objc_msgSend must be called through a correctly typed pointer (arm64 ABI).
    objc = _runtime()
    fn = ctypes.cast(objc.objc_msgSend,
                     ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return fn(receiver, objc.sel_registerName(selector.encode()), *args)


def available():
    """Only Qt's native Cocoa platform gives real NSView handles (not offscreen/minimal)."""
    if sys.platform != "darwin":
        return False
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.platformName() == "cocoa"


def ns_window(widget):
    """The NSWindow behind a (shown) Qt top-level widget, or None."""
    if not available():
        return None
    view = int(widget.winId())  # Qt's winId() on macOS (cocoa) is the NSView pointer
    return _send(view, "window") if view else None


def show_on_all_spaces(widget, enabled=True):
    """Keep ``widget`` on every Space and above full-screen apps. Returns success."""
    if not available():
        return False
    try:
        window = ns_window(widget)
        if not window:
            return False
        behavior = _send(window, "collectionBehavior", ctypes.c_ulong)
        if enabled:
            behavior = (behavior & ~CONFLICTING) | ALL_SPACES_BEHAVIOR
        else:
            behavior &= ~ALL_SPACES_BEHAVIOR
        _send(window, "setCollectionBehavior:", None, (ctypes.c_ulong,), behavior)
        if enabled:
            # Qt makes Qt::Tool windows NSPanels but not non-activating ones.
            if _is_panel(window):
                mask = _send(window, "styleMask", ctypes.c_ulong)
                _send(window, "setStyleMask:", None, (ctypes.c_ulong,), mask | NONACTIVATING_PANEL)
            _send(window, "setLevel:", None, (ctypes.c_long,), STATUS_WINDOW_LEVEL)
        return True
    except (OSError, AttributeError, ValueError) as err:  # never break the overlay over this
        log.warning("could not pin overlay to all Spaces: %s", err)
        return False


def window_state(widget):
    """(collectionBehavior, level) for diagnostics and tests."""
    window = ns_window(widget)
    return (_send(window, "collectionBehavior", ctypes.c_ulong),
            _send(window, "level", ctypes.c_long))
