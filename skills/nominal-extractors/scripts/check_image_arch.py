#!/usr/bin/env python3
"""Check that a `docker save` tarball is built for the architecture Nominal runs.

Nominal runs extractor images on amd64, and `register_image` does not inspect the tarball's
architecture: an arm64 image (the default on Apple Silicon) registers and activates
successfully, then fails at ingest with an exec format error. That failure surfaces long
after the mistake, in a job log, so it is worth catching before the upload.

Usage:
    python check_image_arch.py image.tar
    python check_image_arch.py image.tar --expect arm64   # if you know what you're doing

Exits 0 when every image in the tarball matches, 1 when any doesn't, 2 when the tarball
can't be understood (treat that as "check it by hand", not as a pass).

`docker inspect <tag> --format '{{.Architecture}}'` is simpler when the image is still in
the local daemon. This script exists for the case the daemon isn't there — CI that only has
the artifact, or a tarball someone handed you.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from typing import Any


class TarballError(Exception):
    """The tarball isn't a layout this script understands."""


def _read_json(tar: tarfile.TarFile, name: str) -> Any:
    try:
        member = tar.extractfile(name)
    except KeyError as ex:
        raise TarballError(f"{name} is not in the tarball") from ex
    if member is None:
        raise TarballError(f"{name} is not a regular file")
    try:
        return json.load(member)
    except json.JSONDecodeError as ex:
        raise TarballError(f"{name} is not valid JSON: {ex}") from ex


def _blob_path(digest: str) -> str:
    """Map an OCI descriptor digest ("sha256:abc...") to its path inside the tarball."""
    algorithm, _, hex_digest = digest.partition(":")
    if not algorithm or not hex_digest:
        raise TarballError(f"malformed digest {digest!r}")
    return f"blobs/{algorithm}/{hex_digest}"


def _architectures_from_oci(tar: tarfile.TarFile) -> list[str]:
    """Read architectures from an OCI layout (`index.json` + `blobs/`).

    An index entry usually carries a `platform`, but a single-image save may omit it, so fall
    back to following the manifest to its config blob, which always has `architecture`.
    """
    index = _read_json(tar, "index.json")
    manifests = index.get("manifests") or []
    if not manifests:
        raise TarballError("index.json lists no manifests")

    architectures = []
    for descriptor in manifests:
        platform = descriptor.get("platform") or {}
        if platform.get("architecture"):
            architectures.append(platform["architecture"])
            continue
        digest = descriptor.get("digest")
        if not digest:
            raise TarballError("a manifest descriptor has neither platform nor digest")
        manifest = _read_json(tar, _blob_path(digest))
        # A nested index (a manifest list saved as one entry) needs the same treatment; one
        # level is enough for anything `docker save` produces.
        if nested := manifest.get("manifests"):
            for entry in nested:
                nested_platform = entry.get("platform") or {}
                if nested_platform.get("architecture"):
                    architectures.append(nested_platform["architecture"])
            continue
        config_digest = (manifest.get("config") or {}).get("digest")
        if not config_digest:
            raise TarballError(f"manifest {digest} has no config descriptor")
        config = _read_json(tar, _blob_path(config_digest))
        if not config.get("architecture"):
            raise TarballError(f"config {config_digest} declares no architecture")
        architectures.append(config["architecture"])
    return architectures


def _architectures_from_legacy(tar: tarfile.TarFile) -> list[str]:
    """Read architectures from the legacy layout (`manifest.json` + per-image config JSON)."""
    entries = _read_json(tar, "manifest.json")
    if not isinstance(entries, list) or not entries:
        raise TarballError("manifest.json is not a non-empty list")

    architectures = []
    for entry in entries:
        config_name = entry.get("Config")
        if not config_name:
            raise TarballError("a manifest.json entry has no Config")
        config = _read_json(tar, config_name)
        if not config.get("architecture"):
            raise TarballError(f"{config_name} declares no architecture")
        architectures.append(config["architecture"])
    return architectures


def architectures(tarball: str) -> list[str]:
    """Return every image architecture in a `docker save` tarball.

    Handles both layouts `docker save` produces: the OCI layout (`index.json` + `blobs/`,
    written by newer Docker with the containerd image store) and the legacy layout
    (`manifest.json` plus a config JSON per image).
    """
    try:
        tar = tarfile.open(tarball)
    except (OSError, tarfile.TarError) as ex:
        raise TarballError(f"cannot open {tarball}: {ex}") from ex
    with tar:
        names = set(tar.getnames())
        if "index.json" in names:
            return _architectures_from_oci(tar)
        if "manifest.json" in names:
            return _architectures_from_legacy(tar)
        raise TarballError("no index.json or manifest.json — is this a `docker save` tarball?")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tarball", help="path to the `docker save` tarball")
    parser.add_argument(
        "--expect",
        default="amd64",
        help="architecture the image must be built for (default: amd64, which is what Nominal runs)",
    )
    args = parser.parse_args()

    try:
        found = architectures(args.tarball)
    except TarballError as ex:
        print(f"could not determine the architecture: {ex}", file=sys.stderr)
        print("check it by hand before registering; do not assume it is correct", file=sys.stderr)
        return 2

    distinct = sorted(set(found))
    if args.expect not in distinct:
        print(f"{args.tarball} contains {', '.join(distinct)}, not {args.expect}", file=sys.stderr)
        print(f"rebuild with: docker build --platform linux/{args.expect} -t <tag> .", file=sys.stderr)
        return 1

    if len(distinct) > 1:
        # The expected architecture is in there, so a registry that selects by platform would
        # run the right image -- but whether Nominal's does is not something this script can
        # know, and a single-architecture tarball removes the question.
        others = ", ".join(arch for arch in distinct if arch != args.expect)
        print(
            f"{args.tarball}: multi-architecture ({', '.join(distinct)}). {args.expect} is present, "
            f"but this relies on the registry selecting it over {others}; prefer saving a single "
            f"{args.expect} image.",
            file=sys.stderr,
        )
        return 0

    print(f"{args.tarball}: {distinct[0]} — ok to register")
    return 0


if __name__ == "__main__":
    sys.exit(main())
