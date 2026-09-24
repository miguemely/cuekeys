"""Command line interface: ``pmm``."""

import argparse
import json
import logging
import sys
import time

from . import __version__, device
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


def cmd_bridge(args):
    """Headless: forward OSC / grandMA / Companion without any window."""
    from .runtime import Runtime

    runtime = Runtime(_load(args.config), port=args.port)

    def show(event, data):
        if event == "log" or args.verbose:
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
    target = device.deploy_config(config, args.drive)
    print("wrote %s" % target)
    return 0


def cmd_install(args):
    copied = device.install_firmware(args.drive, include_boot=not args.no_boot)
    for path in copied:
        print("copied %s" % path)
    hardware = "keybow2040"
    if args.config:
        hardware = _load(args.config)["device"].get("hardware", hardware)
        print("wrote %s" % device.deploy_config(_load(args.config), args.drive))
    missing = device.missing_libraries(args.drive, hardware)
    if missing:
        print("missing libraries in lib/: %s (see README, 'Firmware bundle')" % ", ".join(missing))
    if not args.no_boot:
        print("unplug and replug the keypad once so boot.py takes effect")
    return 0


def cmd_devices(_args):
    drives = device.find_drives()
    for drive in drives:
        print("drive  %s  %s" % (drive, device.board_info(drive)))
    if not drives:
        print("drive  (none found)")
    print("serial %s" % (device.find_data_port() or "(no data port found)"))
    return 0


def cmd_init(args):
    from .examples import example_config

    config = example_config() if args.example else cfg.default_config()
    cfg.save(config, args.output)
    print("wrote %s" % args.output)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="pmm", description="PMK Macro Manager")
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
    sp.add_argument("--port", help="serial data port (default: auto-detect)")
    sp = add("overlay", cmd_overlay, "on-screen overlay + bridge only")
    sp.add_argument("--port")
    sp = add("bridge", cmd_bridge, "headless OSC/grandMA/Companion bridge", config_required=True)
    sp.add_argument("--port")
    add("validate", cmd_validate, "check a layout file", config_required=True)
    sp = add("deploy", cmd_deploy, "write a layout to the keypad", config_required=True)
    sp.add_argument("--drive", help="CIRCUITPY path (default: auto-detect)")
    sp = add("install-firmware", cmd_install, "copy the firmware to the keypad")
    sp.add_argument("--drive")
    sp.add_argument("--no-boot", action="store_true", help="leave boot.py alone")
    add("devices", cmd_devices, "list detected keypads", config=False)
    sp = add("init", cmd_init, "create a new layout file", config=False)
    sp.add_argument("output", nargs="?", default="layout.json")
    sp.add_argument("--example", action="store_true", help="include a demo layout")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.command is None:
        args = build_parser().parse_args(["gui"] + list(argv or sys.argv[1:]))
    try:
        return args.func(args) or 0
    except (OSError, RuntimeError) as err:
        print("error: %s" % err, file=sys.stderr)
        return 2
