# Contributing

Thanks for helping. This guide covers setup, day-to-day work, testing, and how changes get released.
AI agents should also read [AGENTS.md](AGENTS.md).

## Setup

```bash
git clone <repo> && cd pimoroni-macro-manager
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # PySide6, pytest, pytest-qt, ruff
.venv/bin/pmm gui examples/demo-layout.json
```

Python 3.10–3.13 is supported (CI tests all four). You don't need a keypad for most work: the
editor, overlay and all tests run without one.

## Day-to-day

| Task | Command |
|---|---|
| Run all tests | `.venv/bin/python -m pytest -q` |
| One file / test | `.venv/bin/python -m pytest tests/test_engine.py -k tap_hold -q` |
| Lint (and auto-fix imports) | `.venv/bin/ruff check .` / `.venv/bin/ruff check --fix .` |
| List device profiles | `.venv/bin/pmm profiles` |
| Try a plugin profile | `PMM_DEVICE_PATH=examples/devices .venv/bin/pmm profiles` |
| Build the firmware zip | `python scripts/build_firmware_bundle.py --out dist` |
| Build a desktop app | `pip install -e ".[build]" && python packaging/build_app.py` |

**Code style:**
- Ruff (`pyproject.toml`) with a line length of 120.
- Match the surrounding code: small functions, and docstrings that explain *why*.
- In `firmware/`, stick to the CircuitPython subset ([AGENTS.md](AGENTS.md#invariants-dont-break-these)).

## Testing

- **Firmware logic:** `engine.py` and `midi.py` import on desktop Python (`tests/conftest.py` adds
  `firmware/lib` to `sys.path`). Drive the engine with a fake clock and backend; see
  `tests/test_engine.py`.
- **Drivers:** stub `board`, `keypad` and `neopixel` in `sys.modules` (`tests/test_drivers.py`).
- **Host logic:** `Runtime(config, link=FakeLink(), satellite_factory=FakeSatellite)`. Call
  `runtime._on_message({...})` to simulate the keypad.
- **Network clients:** start a local fake server on `127.0.0.1:0` (see `test_companion.py`,
  `test_osc_grandma.py`). Never a real Companion or console.
- **GUI:** pytest-qt with the offscreen platform. Use the `window` fixture in `tests/test_gui.py`;
  it patches the "Save changes?" prompt, which would otherwise block the test run forever.

### Visual checks

Tests can't judge looks. For UI changes, render offscreen and look at the image:

```python
# QT_QPA_PLATFORM=offscreen .venv/bin/python shot.py
import sys; sys.path.insert(0, "tests")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pmk_macro_manager.gui.theme import apply; apply(app)
from pmk_macro_manager.examples import example_config
from pmk_macro_manager.runtime import Runtime
from pmk_macro_manager.gui.common import RuntimeSignals
from pmk_macro_manager.gui.editor import MainWindow
from test_runtime import FakeLink, FakeSatellite
rt = Runtime(example_config("adafruit_macropad"), link=FakeLink(False), satellite_factory=FakeSatellite)
win = MainWindow(rt, RuntimeSignals(rt)); win._confirm_discard = lambda: True
win.resize(1280, 800); win.show(); app.processEvents()
win.grab().save("editor.png"); win.overlay.grab().save("overlay.png")
```

Native-window behaviour (macOS Spaces, full screen, multiple displays) needs a probe on the real
platform. See [docs/platform-notes.md](docs/platform-notes.md).

### Hardware testing

For changes to firmware, drivers, LEDs or key handling:

1. `pmm install-firmware --no-boot --drive <CIRCUITPY> <layout.json>`. Only drop `--no-boot` if
   `boot.py` changed, and then unplug and replug.
2. Watch the console port (the non-data CDC port, 115200 baud) for tracebacks. Ctrl+C then Ctrl+D
   reloads.
3. Check each of these:
   - [ ] LEDs show the layer's colours; white looks white after calibration.
   - [ ] Each key highlights on the overlay and in the editor while held; no double presses.
   - [ ] A key combo, typed text and a media key work in another app.
   - [ ] Layer key: tap goes to the next layer, holding returns to the first.
   - [ ] Companion layer: Companion's buttons show on the pad and overlay, presses reach Companion,
         and page keys work.
   - [ ] Unplug and replug: the app reconnects by itself.
4. Say in the MR what you tested, on what board and firmware version.

## Docs to update with a change

| You changed | Update |
|---|---|
| Something user-visible | `README.md`, `CHANGELOG.md` |
| Serial messages | `docs/protocol.md` |
| Profile or driver fields | `docs/devices.md` |
| Architecture or threading | `docs/architecture.md` |
| Found a platform quirk | `docs/platform-notes.md` |
| Left something unfinished | `docs/roadmap.md` |

## Commits and merge requests

- Commit messages: an imperative summary line of 72 characters or fewer ("Add MacroPad encoder
  support"), then a body that explains *why* and anything non-obvious.
- Keep MRs focused. Include tests, and screenshots for UI changes.
- CI must be green: ruff, pytest on 3.10–3.13, wheel and firmware bundle builds.

## CI and releases

`.gitlab-ci.yml` stages:

1. **lint:** ruff, plus a check on tags that the tag matches the version.
2. **test:** a pytest matrix.
3. **build:** the wheel and the firmware zip.
4. **package:** PyInstaller apps for Linux, Windows and macOS. These run on tags, and can be started
   by hand on the default branch.
5. **release:** uploads to the Generic Package Registry and creates a GitLab Release. An optional
   manual PyPI job runs when `PYPI_TOKEN` is set.

**Runner variables:**
- `WINDOWS_RUNNER_TAG` and `MACOS_RUNNER_TAG`. GitLab-hosted macOS runners need Premium or
  Ultimate; otherwise point this at a self-hosted Mac.
- `GITHUB_TOKEN`: avoids GitHub API rate limits when building the firmware zip.
- `ADAFRUIT_BUNDLE` and `PMK_REF`: pin the library versions.

**To release:**
1. Bump `__version__` in `src/pmk_macro_manager/__init__.py`.
2. Update `CHANGELOG.md`.
3. Tag `vX.Y.Z` and push the tag.
