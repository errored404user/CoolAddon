"""Install-packaging tests: manifest, version match, ZIP layouts, server startup."""

import importlib.util
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    spec = importlib.util.spec_from_file_location(
        "install_build", ROOT / "install" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestInstallPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = _load_build()

    def test_manifest_valid(self):
        manifest, errors = self.build.read_manifest()
        self.assertEqual(errors, [], errors)
        self.assertEqual(manifest["id"], "blender_ai_connection")
        self.assertEqual(manifest["type"], "add-on")
        self.assertIn("network", manifest.get("permissions", []))

    def test_versions_match(self):
        version, errors, _warnings = self.build.validate()
        self.assertEqual(errors, [], errors)
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_zip_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            zips = self.build.build_all(Path(tmp))
            self.assertEqual(len(zips), 2)
            by_name = {p.name: p for p in zips}
            ext = [p for n, p in by_name.items() if "legacy" not in n][0]
            legacy = [p for n, p in by_name.items() if "legacy" in n][0]
            with zipfile.ZipFile(ext) as archive:
                names = archive.namelist()
                # Extension format: manifest + module at ZIP root.
                self.assertIn("blender_manifest.toml", names)
                self.assertIn("__init__.py", names)
                self.assertFalse(any("__pycache__" in n for n in names),
                                 "bytecode leaked into extension zip")
            with zipfile.ZipFile(legacy) as archive:
                names = archive.namelist()
                # Legacy format: everything nested under the addon folder.
                self.assertIn("blender_ai_connection/__init__.py", names)
                self.assertTrue(all(n.startswith("blender_ai_connection/")
                                    for n in names), names[:5])

    def test_server_refuses_occupied_port(self):
        from extension import server as ext_server
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        try:
            port = sock.getsockname()[1]
            code = ext_server.main(["--host", "127.0.0.1", "--port", str(port)])
            self.assertEqual(code, 2)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
