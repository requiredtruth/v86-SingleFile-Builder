import json
from pathlib import Path
import tempfile
import unittest

from v86_singlefile.builder import REQUIRED_ASSETS, build, cache_assets, digest, fetch_asset, load_config, validate_output


class BuilderTests(unittest.TestCase):
    def fixture(self, root: Path):
        assets = {}
        for index, name in enumerate(REQUIRED_ASSETS):
            path = root / name
            path.write_bytes((f"synthetic-{index}-{name}\n" * 3).encode())
            assets[name] = {"path": name, "sha256": digest(path), "source": "test fixture", "license": "CC0-1.0 test fixture"}
        config = {"name": "Test </script> VM", "medium": "cdrom", "memory_mb": 64, "vga_memory_mb": 8, "acpi": False, "cmdline": "", "notes": "offline fixture", "assets": assets}
        path = root / "config.json"; path.write_text(json.dumps(config))
        return path

    def test_complete_build_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = load_config(self.fixture(root)); output = root / "vm.html"
            result = build(config, output, root / "cache")
            manifest = validate_output(output)
            self.assertEqual(manifest["format"], "v86-singlefile-v1")
            self.assertEqual(result["sha256"], digest(output))
            self.assertNotIn("</script> VM", output.read_text())

    def test_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = load_config(self.fixture(root))
            a, b = root / "a.html", root / "b.html"
            build(config, a, root / "cache"); build(config, b, root / "cache")
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = load_config(self.fixture(root))
            config["assets"]["v86.wasm"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"): build(config, root / "bad.html")

    def test_license_and_source_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = load_config(self.fixture(root))
            config["assets"]["os-image.bin"]["license"] = ""
            with self.assertRaisesRegex(ValueError, "license is required"): build(config, root / "bad.html")

    def test_cache_detects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = load_config(self.fixture(root))
            from v86_singlefile.builder import validate_config
            assets = validate_config(config); cached = cache_assets(assets, root / "cache")
            cached[0].path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "cached asset is corrupt"): cache_assets(assets, root / "cache")

    def test_fetch_rejects_non_https_before_network(self):
        with self.assertRaisesRegex(ValueError, "https"):
            fetch_asset("http://example.invalid/a", "0" * 64, "/tmp/never-written")

    def test_output_has_no_runtime_external_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / "vm.html"
            build(load_config(self.fixture(root)), output)
            runtime = output.read_text().split("<script>", 1)[-1]
            self.assertNotIn("https://", runtime)


if __name__ == "__main__": unittest.main()
