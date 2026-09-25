# Contributing

Thanks for helping. This guide covers setup, day-to-day work, testing, and how changes get released.
AI agents should also read [AGENTS.md](AGENTS.md).

## Setup

```bash
git clone <repo> && cd cuekeys
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # PySide6, pytest, pytest-qt, ruff
.venv/bin/cuekeys gui examples/demo-layout.json
```

Python 3.10–3.13 is supported (CI tests all four). You don't need a keypad for most work: the
editor, overlay and all tests run without one.

## Day-to-day

| Task | Command |
|---|---|
| Run all tests | `.venv/bin/python -m pytest -q` |
| One file / test | `.venv/bin/python -m pytest tests/test_engine.py -k tap_hold -q` |
| Lint (and auto-fix imports) | `.venv/bin/ruff check .` / `.venv/bin/ruff check --fix .` |
| List device profiles | `.venv/bin/cuekeys profiles` |
| Try a plugin profile | `CUEKEYS_DEVICE_PATH=examples/devices .venv/bin/cuekeys profiles` |
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
from cuekeys.gui.theme import apply; apply(app)
from cuekeys.examples import example_config
from cuekeys.runtime import Runtime
from cuekeys.gui.common import RuntimeSignals
from cuekeys.gui.editor import MainWindow
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

1. `cuekeys install-firmware --no-boot --drive <CIRCUITPY> <layout.json>`. Only drop `--no-boot` if
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
4. Say in the PR what you tested, on what board and firmware version.

## Docs to update with a change

| You changed | Update |
|---|---|
| Something user-visible | `README.md`, `CHANGELOG.md` |
| Serial messages | `docs/protocol.md` |
| Profile or driver fields | `docs/devices.md` |
| Architecture or threading | `docs/architecture.md` |
| Found a platform quirk | `docs/platform-notes.md` |
| Left something unfinished | `docs/roadmap.md` |

## Commits and pull requests

- Commit messages: an imperative summary line of 72 characters or fewer ("Add MacroPad encoder
  support"), then a body that explains *why* and anything non-obvious.
- Keep PRs focused. Include tests, and screenshots for UI changes.
- CI must be green: ruff, pytest on 3.10–3.13, wheel and firmware bundle builds.

## CI and releases

The pipeline exists for both GitHub (`.github/workflows/`) and GitLab (`.gitlab-ci.yml`). Keep them
in step when you change one. The README has a side-by-side table.

- **Every push and PR:** ruff; pytest on Linux × Python 3.10–3.13 plus macOS and Windows; wheel and
  firmware zip builds.
- **On a `vX.Y.Z` tag:** desktop apps for Linux, Windows and macOS, plus the wheel and firmware zip,
  published as a GitHub Release (or GitLab Release and package registry).
  - PyPI publishing is optional: on GitHub, set the repository variable `PUBLISH_PYPI=true` and set
    up PyPI trusted publishing; on GitLab, set `PYPI_TOKEN` and run the manual job.
- **GitLab-only runner variables:** `WINDOWS_RUNNER_TAG` and `MACOS_RUNNER_TAG` (hosted macOS needs
  Premium). Everywhere: `ADAFRUIT_BUNDLE` / `PMK_REF` pin firmware library versions.

**To release:**
1. Bump `__version__` in `src/cuekeys/__init__.py`.
2. Update `CHANGELOG.md`.
3. Optional but recommended: do a dry run with
   `gh workflow run release.yml --ref main` (or Actions → Release → Run workflow). It builds the
   wheel, the firmware zip and the three desktop apps, smoke-tests each app and collects the release
   assets, but publishes nothing.
4. Tag `vX.Y.Z` and push the tag. That's the only thing that publishes a release (and PyPI, if
   enabled).

Dependabot groups its updates into one PR per ecosystem (Python, GitHub Actions). Merge those like
any other PR once CI is green. Action major-version bumps that only affect `release.yml` aren't
covered by CI, so do a release dry run for those.

## Licensing of contributions

The project is dual-licensed: [PolyForm Noncommercial 1.0.0](LICENSE) for everyone, and separate
commercial licenses sold by the copyright holder ([COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)).
Contributed code can only be included in the commercial licenses if the contributor grants those
rights. So:

- **Every contribution needs the project's Contributor License Agreement (CLA).** You keep your
  copyright, and grant the maintainers the right to distribute your contribution under both the
  non-commercial and commercial licenses.
- The PR template has a checkbox for this, and a CLA bot may ask you to sign once.
- New source files get the header `# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0`
  (firmware files already carry it).
- Only add dependencies whose licenses allow this model: permissive (MIT, BSD, Apache-2.0, ISC,
  PSF) or LGPL used as a separately replaceable library. **Don't add GPL or AGPL dependencies**
  without asking first, because they'd conflict with the non-commercial and commercial licensing.
  Record every new distributed dependency in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
