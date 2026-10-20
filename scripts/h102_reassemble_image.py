#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_reassemble_image.py
@brief      Reassemble and verify the released H102 1.2.0 compressed SD image.
@details    Accept only the fixed release identity and its three regular-file parts.
            Publish a new image filename only after part and full-image hashes pass.
            Never overwrite files, access block devices or write an SD card. Keep a
            partial file on failure for diagnosis; it is not a verified image.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-20
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

IMAGE = "LogicRF-Hawk-H102-Kuiper-1.2.0-2024.1.img.xz"
SIZE = 2759144392
SHA256 = "5a09380de3cea3219cc2ffb2cff2a2281e03b5e1c2fee2070c4e77aa9cd170a7"
PART_SIZE = 1024 ** 3
BLOCK_SIZE = 1024 ** 2
"""Fixed release identity, 1-GiB segments and bounded 1-MiB copy buffers."""


def load_manifest(path: Path) -> list[dict]:
    """Validate the fixed image and canonical part layout before opening any output."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if (value.get("schema") != 1 or value.get("image") != IMAGE or
            value.get("bytes") != SIZE or value.get("sha256") != SHA256):
        raise ValueError("RELEASE_IDENTITY_MISMATCH")
    parts = value.get("parts")
    if not isinstance(parts, list) or len(parts) != 3:
        raise ValueError("EXACTLY_THREE_PARTS_REQUIRED")
    for index, entry in enumerate(parts, 1):
        size = PART_SIZE if index < 3 else SIZE - 2 * PART_SIZE
        digest = entry.get("sha256", "")
        if (entry.get("name") != IMAGE + f".part{index:02d}" or entry.get("bytes") != size or
                len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError("PART_LAYOUT_MISMATCH")
    return parts


def assemble(manifest: Path, directory: Path, output: Path | None) -> dict:
    """Verify held regular inputs and optionally assemble a new complete image.

    All parts and their sizes are checked before output creation. Copy and hash
    through the same open FDs, rechecking input metadata afterward. On POSIX,
    reject symlinks without following them. Retain incomplete output on error.
    """
    entries = load_manifest(manifest)
    inputs = []
    partial = None
    result_file = None
    try:
        for entry in entries:
            path = directory / entry["name"]
            if path.is_symlink():
                raise ValueError("PART_SYMLINK_NOT_ALLOWED")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                         getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
            source = os.fdopen(fd, "rb")
            inputs.append((entry, source, os.fstat(fd)))
            saved = inputs[-1][2]
            if not stat.S_ISREG(saved.st_mode) or saved.st_size != entry["bytes"]:
                raise ValueError("PART_TYPE_OR_SIZE_MISMATCH: " + entry["name"])
        if output is not None:
            if output.name != IMAGE or output.exists() or output.is_symlink():
                raise ValueError("NEW_RELEASE_IMAGE_FILENAME_REQUIRED")
            fd, name = tempfile.mkstemp(prefix=IMAGE + ".", suffix=".partial", dir=output.parent)
            partial = Path(name)
            result_file = os.fdopen(fd, "wb")
        whole = hashlib.sha256()
        total = 0
        for entry, source, saved in inputs:
            digest = hashlib.sha256()
            count = 0
            while block := source.read(BLOCK_SIZE):
                count += len(block)
                total += len(block)
                if count > entry["bytes"]:
                    raise ValueError("PART_GREW_DURING_READ")
                digest.update(block)
                whole.update(block)
                if result_file is not None:
                    written = result_file.write(block)
                    if written != len(block):
                        raise OSError("SHORT_OUTPUT_WRITE")
            current = os.fstat(source.fileno())
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if identity(current) != identity(saved):
                raise ValueError("PART_CHANGED_DURING_READ")
            if count != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                raise ValueError("PART_SHA256_MISMATCH: " + entry["name"])
        if total != SIZE or whole.hexdigest() != SHA256:
            raise ValueError("COMPLETE_IMAGE_SHA256_MISMATCH")
        if result_file is not None:
            result_file.flush()
            os.fsync(result_file.fileno())
            result_file.close()
            result_file = None
            # Atomic publication without replacing a file created by another process.
            os.link(partial, output)
            partial.unlink()
            partial = None
            if os.name == "posix":
                fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        return {"status": "PASS_IMAGE_REASSEMBLED" if output else "PASS_PARTS_AND_IMAGE_HASH",
                "image": IMAGE, "bytes": total, "sha256": whole.hexdigest(),
                "output": str(output) if output else None, "sd_written": False}
    finally:
        if result_file is not None:
            result_file.close()
        for _, source, _ in inputs:
            source.close()
        if partial is not None:
            print(json.dumps({"unverified_partial_retained": str(partial)}), flush=True)


def main() -> int:
    """Require explicit assembly or verify-only mode; report failure without writing a card."""
    parser = argparse.ArgumentParser(description="Reassemble the SHA-pinned H102 1.2.0 SD image")
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("image-parts.json"))
    parser.add_argument("--directory", type=Path, help="Directory containing all three downloaded parts")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="New full .img.xz filename; never overwritten")
    mode.add_argument("--verify-only", action="store_true", help="Verify all parts and the full hash without output")
    args = parser.parse_args()
    try:
        result = assemble(args.manifest, args.directory or args.manifest.parent, args.output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error), "sd_written": False}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# End of file: h102_reassemble_image.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
