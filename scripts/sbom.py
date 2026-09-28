#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CueKeys-Source-Available-Reciprocal-1.0
"""Write a CycloneDX 1.5 SBOM (JSON) for what a CueKeys build ships.

    python scripts/sbom.py --out dist/cuekeys-0.1.0-linux-x86_64.cdx.json [--app]

Lists CueKeys and its runtime dependency closure (``cuekeys`` + the ``gui``
extra) as installed in the current environment, with versions, licences and
package URLs. Build-only tools (PyInstaller, pytest, ...) are not included,
except that ``--app`` adds what a PyInstaller app bundle carries besides Python
packages: the Python runtime, Qt, and the PyInstaller bootloader.

The firmware bundle's SBOM is written by ``build_firmware_bundle.py`` with the
helpers below.
"""

import argparse
import datetime
import json
import platform
import re
import sys
import uuid
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "cuekeys"
PROJECT_LICENSE = "LicenseRef-CueKeys-Source-Available-Reciprocal-1.0"
EXTRAS = ("gui",)

# Trove classifier -> SPDX id, for packages without License-Expression metadata.
CLASSIFIER_SPDX = {
    "MIT License": "MIT",
    "BSD License": "BSD-3-Clause",
    "Apache Software License": "Apache-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-3.0-only",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "ISC License (ISCL)": "ISC",
}


def version():
    text = (ROOT / "src" / "cuekeys" / "__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


# ----------------------------------------------------------------- CycloneDX helpers
def component(name, version, licenses=(), purl=None, ctype="library", supplier=None, description=None):
    comp = {"type": ctype, "bom-ref": purl or "%s@%s" % (name, version), "name": name, "version": version}
    if supplier:
        comp["supplier"] = {"name": supplier}
    if description:
        comp["description"] = description
    lic = [license_entry(item) for item in licenses if item]
    if lic:
        comp["licenses"] = lic
    if purl:
        comp["purl"] = purl
    return comp


def license_entry(text):
    text = text.strip()
    # CycloneDX only allows SPDX list ids in "id"; custom LicenseRef-… ids go in an expression.
    if " WITH " in text or " OR " in text or " AND " in text or text.startswith("LicenseRef-"):
        return {"expression": text}
    if re.fullmatch(r"[A-Za-z0-9.+-]+", text):
        return {"license": {"id": text}}
    return {"license": {"name": text}}


def bom(root, components, dependencies=None, properties=None):
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:%s" % uuid.uuid4(),
        "version": 1,
        "metadata": {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
            "tools": {"components": [{"type": "application", "name": "cuekeys scripts/sbom.py",
                                      "version": version()}]},
            "component": root,
        },
        "components": components,
    }
    if properties:
        doc["metadata"]["properties"] = [{"name": k, "value": str(v)} for k, v in properties.items()]
    if dependencies:
        doc["dependencies"] = [{"ref": ref, "dependsOn": sorted(set(deps))} for ref, deps in dependencies.items()]
    return doc


def write(doc, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out


# ----------------------------------------------------------------- Python packages
def _requirements(dist, extras=()):
    """Names of the packages ``dist`` needs (with ``extras``) on this platform."""
    try:
        from packaging.requirements import Requirement
    except ImportError:              # packaging is almost always there; stay usable without it
        Requirement = None           # noqa: N806
    names = []
    for line in dist.requires or ():
        if Requirement is not None:
            req = Requirement(line)
            if req.marker is not None:
                envs = [{"extra": e} for e in (extras or ("",))]
                if not any(req.marker.evaluate(env) for env in envs):
                    continue
            names.append((req.name, tuple(req.extras)))
        else:
            name = re.match(r"[A-Za-z0-9._-]+", line).group(0)
            marker = line.partition(";")[2]
            extra = re.search(r"extra\s*==\s*['\"]([^'\"]+)", marker)
            if extra and extra.group(1) not in extras:
                continue
            names.append((name, ()))
    return names


def _dist_licenses(dist):
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return [expression]
    found = []
    for classifier in meta.get_all("Classifier") or ():
        if classifier.startswith("License :: "):
            label = classifier.split(" :: ")[-1]
            found.append(CLASSIFIER_SPDX.get(label, label))
    if found:
        return sorted(set(found))
    text = (meta.get("License") or "").strip()
    return [text] if text and "\n" not in text and len(text) < 80 else []


def python_components(project=PROJECT, extras=EXTRAS):
    """(root component, [components], dependency graph) for ``project`` as installed."""
    root_dist = metadata.distribution(project)
    seen, order, graph = {}, [], {}
    queue = [(root_dist, tuple(extras))]
    while queue:
        dist, dist_extras = queue.pop(0)
        key = normalize(dist.metadata["Name"])
        if key in seen:
            continue
        seen[key] = dist
        order.append(dist)
        deps = []
        for name, req_extras in _requirements(dist, dist_extras):
            try:
                child = metadata.distribution(name)
            except metadata.PackageNotFoundError:
                continue                      # optional on this platform / not installed
            deps.append(child)
            queue.append((child, req_extras))
        graph[key] = deps

    def purl(dist):
        return "pkg:pypi/%s@%s" % (normalize(dist.metadata["Name"]), dist.version)

    root = component(root_dist.metadata["Name"], root_dist.version, [PROJECT_LICENSE], purl(root_dist),
                     ctype="application", supplier="Miguel Rodriguez",
                     description=root_dist.metadata.get("Summary"))
    root["licenses"] = [license_entry(PROJECT_LICENSE)]            # not a PyPI classifier
    components = [component(d.metadata["Name"], d.version, _dist_licenses(d), purl(d))
                  for d in order[1:]]
    dependencies = {purl(seen[k]): [purl(c) for c in children] for k, children in graph.items()}
    return root, components, dependencies


def app_components():
    """Non-package parts of a PyInstaller app: Python runtime, Qt, bootloader."""
    extra = [component("CPython", platform.python_version(), ["PSF-2.0"],
                       "pkg:generic/python@%s" % platform.python_version(), ctype="framework",
                       supplier="Python Software Foundation")]
    try:
        from PySide6.QtCore import qVersion

        extra.append(component("Qt", qVersion(), ["LGPL-3.0-only"], "pkg:generic/qt@%s" % qVersion(),
                               ctype="framework", supplier="The Qt Company",
                               description="Qt libraries shipped inside PySide6-Essentials"))
    except ImportError:
        pass
    try:
        pyinstaller = metadata.version("pyinstaller")
        extra.append(component("PyInstaller bootloader", pyinstaller,
                               ["GPL-2.0-or-later WITH Bootloader-exception"],
                               "pkg:pypi/pyinstaller@%s" % pyinstaller,
                               description="Executable stub that starts the bundled Python"))
    except metadata.PackageNotFoundError:
        pass
    return extra


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, help="output .cdx.json file")
    parser.add_argument("--app", action="store_true", help="include the Python runtime, Qt and bootloader")
    parser.add_argument("--target", help="build target recorded in the SBOM, e.g. linux-arm64")
    args = parser.parse_args()

    root, components, dependencies = python_components()
    if args.app:
        extra = app_components()
        components += extra
        pyside = next((ref for ref in dependencies if ref.startswith("pkg:pypi/pyside6-essentials@")), None)
        for comp in extra:
            parent = pyside if comp["name"] == "Qt" and pyside else root["bom-ref"]
            dependencies.setdefault(parent, []).append(comp["bom-ref"])
    props = {"cuekeys:target": args.target or "%s-%s" % (sys.platform, platform.machine())}
    print("wrote %s (%d components)" % (write(bom(root, components, dependencies, props), args.out),
                                        len(components)))


if __name__ == "__main__":
    main()
