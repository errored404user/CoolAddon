#!/usr/bin/env python3
"""Build installable ZIPs for the Blender AI Connection addon (stdlib only).

Produces two files in dist/:
  - BlenderAIConnection-<ver>.zip         Blender 4.2+ Extension (manifest at zip root)
  - BlenderAIConnection-legacy-<ver>.zip  Blender 3.6-4.1 legacy add-on (folder at zip root)

Usage:
    python install/build.py [--dist DIR] [--check]

--check only validates (manifest, version match, required files) without
writing ZIPs. Used by the test-suite.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
ADDON = ROOT / "blender_ai_connection"
DIST = ROOT / "dist"

REQUIRED_MANIFEST_KEYS = ("schema_version", "id", "version", "name",
                          "tagline", "maintainer", "type", "license")
SKIP_DIR_NAMES = {"__pycache__", ".git"}
SKIP_FILE_NAMES = {".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

# Allowed add-on tags (Blender manual — Extensions Tags).
ADDON_TAGS = {"3D View", "Add Curve", "Add Mesh", "Animation", "Bake",
              "Camera", "Compositing", "Development", "Game Engine",
              "Geometry Nodes", "Grease Pencil", "Import-Export",
              "Lighting", "Material", "Modeling", "Mesh", "Node", "Object",
              "Paint", "Pipeline", "Physics", "Render", "Rigging", "Scene",
              "Sculpt", "Sequencer", "System", "Text Editor", "Tracking",
              "User Interface", "UV"}
PERMISSION_KEYS = {"files", "network", "clipboard", "camera", "microphone"}


def validate_manifest_rules(manifest: dict) -> list:
    """Official packaging rules. Returns a list of error strings."""
    errors: list = []
    pkg_id = str(manifest.get("id", ""))
    if pkg_id and not re.fullmatch(r"[a-z][a-z0-9_]*", pkg_id):
        errors.append(f"manifest id {pkg_id!r} must be lowercase "
                      "(letters, digits, underscores)")
    tagline = str(manifest.get("tagline", ""))
    if tagline:
        if tagline[-1] in ".:;!?":
            errors.append("manifest tagline must not end with punctuation")
        if len(tagline) > 120:
            errors.append(f"manifest tagline too long ({len(tagline)} chars, max 120)")
    tags = manifest.get("tags", []) or []
    unknown = [t for t in tags if t not in ADDON_TAGS]
    if unknown:
        errors.append(f"manifest has unknown add-on tags: {unknown}")
    if manifest.get("type") == "add-on" and "SPDX:GPL-3.0-or-later" not in (
            manifest.get("license", []) or []):
        errors.append("add-ons require license 'SPDX:GPL-3.0-or-later' "
                      "(Blender Extensions Platform rule)")
    permissions = manifest.get("permissions")
    if permissions is not None:
        if not isinstance(permissions, dict):
            errors.append("manifest permissions must be a table, e.g. "
                          '[permissions] network = "reason without period"')
        else:
            for key, reason in permissions.items():
                if key not in PERMISSION_KEYS:
                    errors.append(f"manifest has unknown permission '{key}'")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(f"manifest permission '{key}' needs a reason string")
                elif reason.strip()[-1] in ".:;!?":
                    errors.append(f"manifest permission '{key}' reason must not "
                                  "end with punctuation")
    return errors


def read_manifest() -> tuple:
    """Return (manifest_dict, errors)."""
    path = ADDON / "blender_manifest.toml"
    if not path.is_file():
        return {}, [f"missing {path}"]
    if tomllib is None:
        return {}, ["tomllib needs Python 3.11+ to validate the manifest"]
    try:
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"manifest unreadable: {exc}"]
    errors = [f"manifest missing required key '{key}'"
              for key in REQUIRED_MANIFEST_KEYS
              if not manifest.get(key)]
    if manifest.get("type") != "add-on":
        errors.append(f"manifest type must be 'add-on' (got {manifest.get('type')!r})")
    if manifest.get("id") != ADDON.name:
        errors.append(f"manifest id {manifest.get('id')!r} must match folder name "
                      f"{ADDON.name!r} (addon code looks it up by this name)")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", ""))):
        errors.append("manifest version must look like '1.0.0'")
    errors.extend(validate_manifest_rules(manifest))
    return manifest, errors


def read_bl_info_version() -> str:
    text = (ADDON / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'"version"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)', text)
    if not match:
        return ""
    return ".".join(match.groups())


def validate() -> tuple:
    """Return (version, errors, warnings)."""
    errors: list = []
    warnings: list = []
    if not (ADDON / "__init__.py").is_file():
        errors.append("missing blender_ai_connection/__init__.py")
    manifest, manifest_errors = read_manifest()
    errors.extend(manifest_errors)
    version = str(manifest.get("version", "")) if manifest else ""
    bl_version = read_bl_info_version()
    if not bl_version:
        warnings.append("could not parse bl_info version from __init__.py")
    elif version and bl_version != version:
        errors.append(f"version mismatch: manifest={version} bl_info={bl_version}")
    return version or "0.0.0", errors, warnings


def _iter_addon_files():
    files = []
    for path in sorted(ADDON.rglob("*")):
        if path.is_dir() or path.name in SKIP_FILE_NAMES:
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return files


def build_all(dist_dir: Path = DIST) -> list:
    version, errors, warnings = validate()
    if errors:
        raise SystemExit("build blocked:\n- " + "\n- ".join(errors))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    dist_dir.mkdir(parents=True, exist_ok=True)
    files = _iter_addon_files()
    if not files:
        raise SystemExit("build blocked: no addon files found")

    ext_zip = dist_dir / f"BlenderAIConnection-{version}.zip"
    with zipfile.ZipFile(ext_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ADDON))

    legacy_zip = dist_dir / f"BlenderAIConnection-legacy-{version}.zip"
    with zipfile.ZipFile(legacy_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path(ADDON.name) / path.relative_to(ADDON))

    for path in (ext_zip, legacy_zip):
        print(f"built {path} ({path.stat().st_size // 1024} KB)")
    return [ext_zip, legacy_zip]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build Blender install ZIPs")
    parser.add_argument("--dist", default=str(DIST))
    parser.add_argument("--check", action="store_true",
                        help="Validate only, don't write ZIPs")
    args = parser.parse_args(argv)
    version, errors, warnings = validate()
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        print("FAILED:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print(f"manifest + sources OK (version {version})")
    if not args.check:
        build_all(Path(args.dist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
