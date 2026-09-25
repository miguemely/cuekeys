"""SBOMs for the desktop apps (scripts/sbom.py) and the firmware bundle."""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load(name):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_python_sbom_lists_runtime_dependencies_only(tmp_path):
    sbom = load("sbom")
    root, components, deps = sbom.python_components()
    names = {sbom.normalize(c["name"]) for c in components}
    assert root["name"] == "cuekeys" and root["licenses"] == [{"license": {"id": "PolyForm-Noncommercial-1.0.0"}}]
    assert "pyserial" in names
    assert not names & {"pytest", "ruff", "pyinstaller", "pytest-qt"}      # dev/build tools aren't shipped
    pyserial = next(c for c in components if sbom.normalize(c["name"]) == "pyserial")
    assert pyserial["purl"].startswith("pkg:pypi/pyserial@") and pyserial["licenses"]
    assert all(ref in deps for ref in deps[root["bom-ref"]])                 # graph is closed

    out = sbom.write(sbom.bom(root, components, deps, {"cuekeys:target": "test"}), tmp_path / "x.cdx.json")
    doc = json.loads(out.read_text())
    assert doc["bomFormat"] == "CycloneDX" and doc["specVersion"] == "1.5"
    assert doc["serialNumber"].startswith("urn:uuid:")


def test_license_entries():
    sbom = load("sbom")
    assert sbom.license_entry("MIT") == {"license": {"id": "MIT"}}
    assert sbom.license_entry("LGPL-3.0-only OR GPL-3.0-only") == {"expression": "LGPL-3.0-only OR GPL-3.0-only"}
    assert sbom.license_entry("Some custom licence") == {"license": {"name": "Some custom licence"}}


def test_firmware_sbom_reads_library_versions(tmp_path):
    fw = load("build_firmware_bundle")
    lib = tmp_path / "lib"
    (lib / "adafruit_hid").mkdir(parents=True)
    (lib / "adafruit_hid" / "__init__.py").write_text('__version__ = "6.1.10"\n')
    (lib / "neopixel.py").write_text("__version__ = '6.4.2'\n")
    doc = fw.firmware_sbom(lib, "20260924", "main", "76b4ec6a")
    by_name = {c["name"]: c for c in doc["components"]}
    assert by_name["adafruit_hid"]["version"] == "6.1.10"
    assert by_name["neopixel"]["version"] == "6.4.2"
    assert by_name["adafruit_dotstar"]["version"] == "20260924"             # falls back to the bundle tag
    assert by_name["pmk"]["purl"] == "pkg:github/pimoroni/pmk-circuitpython@76b4ec6a"
    assert doc["metadata"]["component"]["type"] == "firmware"
    assert set(doc["dependencies"][0]["dependsOn"]) == {c["bom-ref"] for c in doc["components"]}
