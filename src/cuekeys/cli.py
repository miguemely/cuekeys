"""Command line interface: ``cuekeys``."""

import argparse
import json
import logging
import sys
import time

from . import __version__, device, devices
from . import config as cfg


def _load(path):
    try:
        return cfg.load(path)
    except (OSError, ValueError) as err:
        sys.exit("cannot read %s: %s" % (path, err))


def cmd_gui(args):
    from .gui.app import run_editor

    return run_editor(args.config, args.port)


def cmd_overlay(args):
    from .gui.app import run_overlay

    return run_overlay(args.config, args.port)


def _store():
    from .keypads import KeypadStore

    return KeypadStore()


def _keypad(uid):
    """Resolve a keypad id given in full, by its short id, or by its name."""
    if uid is None:
        return None
    store = _store()
    known = {u: e for u, e in store.all().items()}
    for info in device.list_keypads():
        known.setdefault(info["uid"], {})
    wanted = uid.strip()
    matches = [u for u, e in known.items()
               if wanted.upper() in (u, u[-8:]) or wanted.lower() == str(e.get("name", "")).lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches and len(wanted) == 16:
        return wanted.upper()
    raise RuntimeError("%s keypad matches %r (see 'cuekeys keypads')" % ("more than one" if matches else "no", uid))


def cmd_bridge(args):
    """Headless: forward OSC / grandMA / Companion without any window."""
    from .runtime import Hub, Runtime

    config = _load(args.config)
    if args.port:
        runtime = Runtime(config, port=args.port, store=_store())
    else:
        # Every connected keypad; each uses its assigned layout, else this one.
        runtime = Hub(default_config=config, store=_store(), layout_loader=cfg.load)
        runtime.default_path = args.config

    def show(event, data):
        if event in ("log", "keypads") or args.verbose:
            print("%s %s" % (event, json.dumps(data, default=str)), flush=True)

    runtime.add_listener(show)
    runtime.start()
    print("bridge running, Ctrl+C to stop", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()
    return 0


def cmd_validate(args):
    problems = cfg.validate(cfg.prune(_load(args.config)))
    for problem in problems:
        print(problem)
    if not problems:
        print("%s: OK" % args.config)
    return 1 if problems else 0


def cmd_deploy(args):
    config = _load(args.config)
    problems = cfg.validate(cfg.prune(config))
    if problems:
        print("\n".join(problems))
        return 1
    uid = _keypad(args.keypad)
    settings = _store().get(uid) if uid else None
    target = device.deploy_config(config, args.drive, uid=uid, keypad=settings)
    print("wrote %s" % target)
    return 0


def cmd_install(args):
    config = _load(args.config) if args.config else None
    uid = _keypad(args.keypad)
    drive = device.pick_drive(args.drive, uid=uid)
    profile = devices.profile_for(config) if config else _detect_profile(drive)
    print("device profile: %s (%s)" % (profile.id, profile.name))
    copied = device.install_firmware(drive, include_boot=not args.no_boot, profile=profile)
    for path in copied:
        print("copied %s" % path)
    if config:
        board_uid = device.board_uid(drive)
        settings = _store().get(board_uid) if board_uid else None
        print("wrote %s" % device.deploy_config(config, drive, keypad=settings))
    missing = device.missing_libraries(drive, profile)
    if missing:
        print("missing libraries in lib/: %s (see README, 'Firmware bundle')" % ", ".join(missing))
    if not args.no_boot:
        print("unplug and replug the keypad once so boot.py takes effect")
    return 0


def _detect_profile(drive):
    board = device.board_id(device.pick_drive(drive))
    matches = devices.match_board(board)
    if len(matches) == 1:
        return matches[0]
    if matches:
        print("board %s matches several profiles (%s); using %s. Pass a layout to choose."
              % (board, ", ".join(p.id for p in matches), matches[0].id))
        return matches[0]
    print("no device profile for board %r; using %s" % (board, devices.DEFAULT_PROFILE))
    return devices.get_profile(devices.DEFAULT_PROFILE)


def cmd_devices(_args):
    drives = device.find_drives()
    for drive in drives:
        board = device.board_id(drive)
        matches = ", ".join(p.id for p in devices.match_board(board)) or "no matching profile"
        uid = device.board_uid(drive)
        print("drive  %s  %s  [%s]%s" % (drive, device.board_info(drive), matches,
                                          "  keypad %s" % uid if uid else ""))
    if not drives:
        print("drive  (none found)")
    keypads = device.list_keypads()
    for info in keypads:
        print("serial %s  keypad %s  (console %s)" % (info["data_port"], info["uid"],
                                                    info["console_port"] or "-"))
    if not keypads:
        print("serial (no data port found)")
    return 0


def cmd_keypads(args):
    """List keypads (connected and remembered); rename, assign layouts, forget."""
    import os
    import time as _time

    from .keypads import short_id

    store = _store()
    if args.action != "list" and not args.keypad:
        raise RuntimeError("which keypad? e.g. cuekeys keypads %s <id|name> ..." % args.action)
    if args.action == "rename":
        uid = _keypad(args.keypad)
        store.update(uid, name=args.value or None)
        print("%s: %s" % (uid, store.name(uid)))
        return 0
    if args.action == "assign":
        uid = _keypad(args.keypad)
        layout = os.path.abspath(args.value) if args.value else None
        if layout:
            _load(layout)                       # must be readable
        store.update(uid, layout=layout)
        print("%s: %s" % (uid, layout or "uses the default layout"))
        return 0
    if args.action == "forget":
        uid = _keypad(args.keypad)
        print("forgot %s" % uid if store.forget(uid) else "%s was not remembered" % uid)
        return 0
    connected = {info["uid"]: info for info in device.list_keypads()}
    known = store.all()
    uids = list(connected) + sorted(u for u in known if u not in connected)
    if not uids:
        print("no keypads connected or remembered")
        return 0
    for uid in uids:
        entry = known.get(uid, {})
        info = connected.get(uid)
        if info:
            where = "connected on %s" % info["data_port"]
        elif entry.get("last_seen"):
            where = "last seen %s" % _time.strftime("%Y-%m-%d %H:%M", _time.localtime(entry["last_seen"]))
        else:
            where = "not connected"
        print("%s  %-8s  %-20s %s" % (uid, short_id(uid), store.name(uid), where))
        if entry.get("layout"):
            print("%s layout %s" % (" " * 30, entry["layout"]))
        if "led_balance" in entry or "led_gamma" in entry:
            print("%s LEDs   gamma %s, balance %s" % (" " * 30, entry.get("led_gamma", "-"),
                                                     entry.get("led_balance", "-")))
    return 0


def cmd_profiles(args):
    for profile in sorted(devices.all_profiles().values(), key=lambda p: p.id):
        tested = "" if profile.tested else "  (untested)"
        print("%-20s %-36s %dx%d, %d keys, driver %s%s" % (
            profile.id, profile.name, profile.cols, profile.rows, profile.num_keys, profile.driver, tested))
        if args.verbose:
            print("%20s %s" % ("", profile.source))
    for error in devices.load_errors():
        print("error: %s" % error)
    print("\nplugin folder: %s" % devices.user_device_dir())
    return 0


def cmd_init(args):
    from .examples import example_config

    profile_id = args.device or devices.DEFAULT_PROFILE
    devices.get_profile(profile_id)  # fail early on unknown ids
    config = example_config(profile_id) if args.example else cfg.default_config()
    config["device"]["profile"] = profile_id
    cfg.save(config, args.output)
    print("wrote %s" % args.output)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="cuekeys", description="CueKeys")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command")

    def add(name, fn, help_text, config=True, config_required=False):
        sp = sub.add_parser(name, help=help_text)
        if config:
            if config_required:
                sp.add_argument("config", help="layout JSON file")
            else:
                sp.add_argument("config", nargs="?", help="layout JSON file")
        sp.set_defaults(func=fn)
        return sp

    sp = add("gui", cmd_gui, "open the editor (default)")
    sp.add_argument("--port", help="use only the keypad on this serial data port (default: all keypads)")
    sp = add("overlay", cmd_overlay, "on-screen overlay + bridge only")
    sp.add_argument("--port")
    sp = add("bridge", cmd_bridge, "headless OSC/grandMA/Companion bridge", config_required=True)
    sp.add_argument("--port")
    add("validate", cmd_validate, "check a layout file", config_required=True)
    sp = add("deploy", cmd_deploy, "write a layout to the keypad", config_required=True)
    sp.add_argument("--drive", help="CIRCUITPY path (default: auto-detect)")
    sp.add_argument("--keypad", help="keypad id, short id or name (several keypads connected)")
    sp = add("install-firmware", cmd_install, "copy the firmware to the keypad")
    sp.add_argument("--drive")
    sp.add_argument("--keypad", help="keypad id, short id or name (several keypads connected)")
    sp.add_argument("--no-boot", action="store_true", help="leave boot.py alone")
    add("devices", cmd_devices, "list detected drives and serial ports", config=False)
    sp = add("keypads", cmd_keypads, "list, rename or assign layouts to keypads", config=False)
    sp.add_argument("action", nargs="?", default="list", choices=("list", "rename", "assign", "forget"))
    sp.add_argument("keypad", nargs="?", help="keypad id, short id or name")
    sp.add_argument("value", nargs="?", help="new name (rename) or layout file (assign; omit to clear)")
    add("profiles", cmd_profiles, "list supported keypad models (device profiles)", config=False)
    sp = add("init", cmd_init, "create a new layout file", config=False)
    sp.add_argument("output", nargs="?", default="layout.json")
    sp.add_argument("--example", action="store_true", help="include a demo layout")
    sp.add_argument("--device", help="device profile id (see 'cuekeys profiles')")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.command is None:
        args = build_parser().parse_args(["gui"] + list(argv or sys.argv[1:]))
    try:
        return args.func(args) or 0
    except (OSError, RuntimeError, KeyError) as err:
        print("error: %s" % str(err).strip("'\""), file=sys.stderr)
        return 2
