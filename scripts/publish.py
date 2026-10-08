#!/usr/bin/env python3
"""Republish verified Cloudified CI IPAs as permanent SideStore source releases."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SOURCE_REPO = "tinyredphoenix/Cloudified-Source"
APP_REPO = "tinyredphoenix/Cloudified"
BUNDLE_ID = "com.tinyredphoenix.Cloudified"
IPA_NAME = "Cloudified-unsigned.ipa"
ICON_URL = f"https://raw.githubusercontent.com/{SOURCE_REPO}/main/icon.png"
PHOTO_PERMISSION = (
    "Cloudified requires photo library access to back up original quality "
    "photos and videos to Google Photos and Telegram."
)


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def digest(path: Path) -> str:
    hash_value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def fetch(url: str, target: Path) -> None:
    for attempt in range(3):
        outcome = command(
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--retry", "2", "--retry-all-errors", "--output", str(target), url,
            check=False,
        )
        if outcome.returncode == 0:
            return
        if attempt < 2:
            time.sleep(3)
    raise RuntimeError(f"Could not fetch public staged IPA: {url}")


def ipa_info(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return plistlib.loads(archive.read("Payload/Cloudified.app/Info.plist"))


def existing_release(tag: str) -> dict | None:
    outcome = command("gh", "api", f"repos/{SOURCE_REPO}/releases/tags/{tag}", check=False)
    if outcome.returncode:
        return None
    return json.loads(outcome.stdout)


def source_app() -> dict:
    return {
        "name": "Cloudified",
        "bundleIdentifier": BUNDLE_ID,
        "developerName": "tinyredphoenix",
        "subtitle": "Original photo and video backup",
        "localizedDescription": (
            "Personal uploader for original photos and videos to Google Photos "
            "and Telegram. This unsigned build is awaiting real iPhone and "
            "cloud-service verification."
        ),
        "iconURL": ICON_URL,
        "tintColor": "#1681EF",
        "category": "photo-video",
        "versions": [],
        "appPermissions": {
            "entitlements": [],
            "privacy": {"NSPhotoLibraryUsageDescription": PHOTO_PERMISSION},
        },
    }


def check_manifest(manifest: dict) -> None:
    if manifest.get("schema") != 1 or not isinstance(manifest.get("runId"), int):
        raise ValueError("Invalid incoming build manifest")
    run_id = manifest["runId"]
    if manifest.get("runURL") != f"https://github.com/{APP_REPO}/actions/runs/{run_id}":
        raise ValueError("Unexpected build run URL")
    if manifest.get("status") not in (
        "success", "failure", "cancelled", "timed_out", "neutral",
        "skipped", "stale", "action_required", "startup_failure",
    ):
        raise ValueError("Unexpected build status")
    if manifest["status"] == "success":
        tag = f"ci-run-{run_id}-untested"
        expected = f"https://github.com/{APP_REPO}/releases/download/{tag}/{IPA_NAME}"
        if (manifest.get("stageURL") != expected or manifest.get("stageTag") != tag
                or manifest.get("bundleIdentifier") != BUNDLE_ID
                or len(manifest.get("sha256", "")) != 64
                or not isinstance(manifest.get("size"), int)):
            raise ValueError("Malformed successful build manifest")


def publish_success(manifest: dict, source: dict) -> dict:
    run_id = manifest["runId"]
    tag = manifest["stageTag"]
    with tempfile.TemporaryDirectory(prefix="cloudified-release-") as scratch:
        ipa = Path(scratch) / IPA_NAME
        fetch(manifest["stageURL"], ipa)
        if ipa.stat().st_size != manifest["size"] or digest(ipa) != manifest["sha256"]:
            raise ValueError(f"Staged IPA size or SHA-256 differs for run {run_id}")
        info = ipa_info(ipa)
        if (info.get("CFBundleIdentifier") != BUNDLE_ID
                or str(info.get("CFBundleShortVersionString")) != manifest["version"]
                or str(info.get("CFBundleVersion")) != manifest["buildVersion"]
                or info.get("CloudifiedRevision") != manifest["headSha"]):
            raise ValueError(f"Staged IPA identity does not match run {run_id}")
        checksum = Path(scratch) / (IPA_NAME + ".sha256")
        checksum.write_text(f"{manifest['sha256']}  {IPA_NAME}\n")
        existing = existing_release(tag)
        if existing:
            assets = {asset["name"]: asset for asset in existing["assets"]}
            asset = assets.get(IPA_NAME)
            if not asset or asset.get("digest") != "sha256:" + manifest["sha256"]:
                raise ValueError("Existing source release differs from verified IPA")
        else:
            command(
                "gh", "release", "create", tag, str(ipa), str(checksum),
                "--repo", SOURCE_REPO,
                "--target", "main",
                "--title", f"Cloudified {manifest['version']} ({manifest['buildVersion']}) — CI build, untested",
                "--notes", (
                    "Unsigned IPA. Compiled and packaged; device and service "
                    f"verification is pending.\n\nBuild: {manifest['runURL']}"
                ),
                "--prerelease",
            )

    if not source["apps"]:
        source["apps"] = [source_app()]
    app = source["apps"][0]
    versions = app["versions"]
    version_url = f"https://github.com/{SOURCE_REPO}/releases/download/{tag}/{IPA_NAME}"
    if not any(item["downloadURL"] == version_url for item in versions):
        if any(item["version"] == manifest["version"] and
               item["buildVersion"] == manifest["buildVersion"] for item in versions):
            raise ValueError("Distinct CI run reused an existing app build number")
        versions.append({
            "version": manifest["version"],
            "buildVersion": manifest["buildVersion"],
            "marketingVersion": f"{manifest['version']} ({manifest['buildVersion']})",
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "localizedDescription": "Unsigned CI build; device and cloud-service verification pending.",
            "downloadURL": version_url,
            "size": manifest["size"],
            "sha256": manifest["sha256"],
            "minOSVersion": "26.0",
        })
        versions.sort(key=lambda item: int(item["buildVersion"]), reverse=True)
    return {"releaseURL": f"https://github.com/{SOURCE_REPO}/releases/tag/{tag}"}


def main() -> None:
    source_path = ROOT / "source.json"
    builds_path = ROOT / "builds.json"
    source = json.loads(source_path.read_text())
    builds = json.loads(builds_path.read_text())
    recorded = {entry["runId"] for entry in builds}
    incoming = sorted((ROOT / "incoming").glob("*.json"), key=lambda path: int(path.stem))
    for path in incoming:
        manifest = json.loads(path.read_text())
        check_manifest(manifest)
        if manifest["runId"] in recorded:
            continue
        detail = publish_success(manifest, source) if manifest["status"] == "success" else {}
        builds.append({
            "runId": manifest["runId"],
            "runNumber": manifest["runNumber"],
            "headSha": manifest["headSha"],
            "status": manifest["status"],
            "runURL": manifest["runURL"],
            **detail,
        })
        recorded.add(manifest["runId"])
    builds.sort(key=lambda item: item["runId"], reverse=True)
    source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    builds_path.write_text(json.dumps(builds, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
