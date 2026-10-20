#!/usr/bin/env python3
"""
Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       compact_h102_image.py
@brief      Install first-boot expansion and headless policy into a compact image copy.
@details
Accept only the product manifest's pinned 49f2 regular IMG and a new artifacts directory.
Use host e2fsprogs/util-linux with a read-only source loop and separate writable output.
Preserve the original image, MBR identity, root start and all data preceding the root.
On failure retain evidence and release resources; offline success is not board qualification.
@author     LogicRF Technologies
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.1
@date       2026-09-30
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


# Fixed input and DOS geometry belong to this candidate lineage, in 512-byte sectors.
SOURCE_SHA = "49f236ee4ec7268892a7ec6bfa59379211b5ab317ff9e6ef88e0f1f0f9c4c492"
SOURCE_BYTES = 31_460_950_016
ROOT_START = 4_218_880
ROOT_BLOCKS = 9 * 1024**3 // 4096
ROOT_SECTORS = ROOT_BLOCKS * 8
IMAGE_NAME = "H102-LogicRF-Kuiper-2025-03-18-2024.1-TX-v3-compact-lab-candidate.img"
OVERLAY_PATHS = (
    "etc/init.d/extend-rootfs-once",
    "etc/rc3.d/S01extend-rootfs-once",
    "usr/local/sbin/h102-grow-rootfs",
    "etc/systemd/system/h102-grow-rootfs.service",
    "etc/systemd/system/multi-user.target.wants/h102-grow-rootfs.service",
    "etc/h102/compact-image",
    "etc/systemd/system/lightdm.service.d/20-h102-desktop-condition.conf",
    "etc/systemd/system/x11vnc.service.d/20-h102-desktop-condition.conf",
    "etc/systemd/system/h102-headless-boot.service",
    "etc/systemd/system/multi-user.target.wants/h102-headless-boot.service",
)
# These two leaves are the only desktop changes permitted in the private copy.
DESKTOP_OVERLAYS = tuple((name, "overlays/h102/systemd/system/" + name.removeprefix("etc/systemd/system/"))
                         for name in OVERLAY_PATHS[6:8])


def digest(path: Path, offset: int = 0, length: int | None = None) -> str:
    """Hash a complete file or byte range and raise on premature EOF."""
    value = hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(offset)
        remaining = length
        while remaining is None or remaining > 0:
            data = stream.read(4 * 1024**2 if remaining is None else min(4 * 1024**2, remaining))
            if not data:
                if remaining not in (None, 0):
                    raise ValueError(f"Unexpected EOF: {path}")
                break
            value.update(data)
            if remaining is not None:
                remaining -= len(data)
    return value.hexdigest()


def parse_mbr(path: Path) -> tuple[bytes, list[dict]]:
    """Read DOS partition entries independently of loop naming or sfdisk formatting."""
    with path.open("rb") as stream:
        sector = stream.read(512)
    if len(sector) != 512 or sector[510:512] != b"\x55\xaa":
        raise ValueError("Missing DOS partition signature")
    entries = []
    for number in range(4):
        entry = sector[446 + 16 * number:462 + 16 * number]
        entries.append({"number": number + 1, "boot": entry[0], "type": entry[4],
                        "start": struct.unpack_from("<I", entry, 8)[0],
                        "size": struct.unpack_from("<I", entry, 12)[0]})
    return sector, entries


def verify_geometry(path: Path, root_sectors: int) -> bytes:
    """Reject unknown layout or disk identity and return the MBR for exact comparison."""
    sector, entries = parse_mbr(path)
    if sector[440:444] != bytes.fromhex("d28622a2"):
        raise ValueError("Unexpected disk identity")
    expected = [(24576, 4194304, 0x0C), (ROOT_START, root_sectors, 0x83), (8192, 16384, 0xA2), (0, 0, 0)]
    for entry, fields in zip(entries, expected):
        if (entry["start"], entry["size"], entry["type"]) != fields or entry["boot"] != 0:
            raise ValueError(f"Unexpected partition: {entry}")
        if (entry["start"] + entry["size"]) * 512 > path.stat().st_size:
            raise ValueError("Partition extends past image")
    return sector


class Builder:
    """Own mounts, loops and logs serially; one instance does not support concurrent calls."""

    def __init__(self, source: Path, output: Path, project: Path):
        """Bind verified paths; build's finally releases temporary resources."""
        self.source, self.output, self.project = source, output, project
        self.evidence = output / "evidence"
        self.image = output / IMAGE_NAME
        self.loops: list[str] = []
        self.mounts: list[Path] = []
        self.temp = Path(tempfile.mkdtemp(prefix="h102-compact-"))
        self.log = self.evidence / "commands.log"

    def run(self, args: list[str], *, privileged: bool = False,
            input_text: str | None = None, accepted: tuple[int, ...] = (0,)) -> str:
        """Run an argument vector without a shell and record output; reject unexpected exit codes."""
        command = (["sudo", "-n"] if privileged else []) + [str(arg) for arg in args]
        with self.log.open("a") as log:
            log.write(json.dumps(command) + "\n")
            log.flush()
            result = subprocess.run(command, input=input_text, text=True, stdout=subprocess.PIPE,
                                    stderr=log, check=False, env={**os.environ, "LC_ALL": "C"})
            log.write(result.stdout + f"\nexit_code={result.returncode}\n")
        if result.returncode not in accepted:
            raise RuntimeError(f"Command failed ({result.returncode}): {command}")
        return result.stdout

    def attach(self, image: Path, readonly: bool = False) -> str:
        """Attach an owned regular image, never an externally supplied block device."""
        command = ["losetup", "--find", "--show", "--partscan"]
        if readonly:
            command.append("--read-only")
        loop = self.run(command + [str(image)], privileged=True).strip()
        self.loops.append(loop)
        self.run(["udevadm", "settle"], privileged=True)
        backfile = self.run(["losetup", "-n", "-O", "BACK-FILE", loop], privileged=True).strip()
        if backfile != str(image):
            raise RuntimeError("Loop backing-file mismatch")
        return loop

    def detach(self, loop: str) -> None:
        """Detach only a loop owned by this instance and preserve detach errors."""
        self.run(["losetup", "-d", loop], privileged=True)
        self.loops.remove(loop)

    def mount(self, device: str, name: str, readonly: bool) -> Path:
        """Mount root with journal replay disabled during read-only verification."""
        destination = self.temp / name
        destination.mkdir(exist_ok=True)
        self.run(["mount", "-o", "ro,noload" if readonly else "rw", device, str(destination)], privileged=True)
        self.mounts.append(destination)
        return destination

    def unmount(self, destination: Path) -> None:
        """Unmount an owned filesystem after the caller completes required synchronization."""
        self.run(["umount", str(destination)], privileged=True)
        self.mounts.remove(destination)

    def install_overlay(self, root: Path) -> None:
        """Replace first-boot setup in the output copy and preserve the old script as evidence."""
        overlay = self.project / "overlays/h102"
        self.run(["cp", str(root / OVERLAY_PATHS[0]), str(self.evidence / "old-extend-rootfs-once")], privileged=True)
        self.run(["rm", str(root / OVERLAY_PATHS[0]), str(root / OVERLAY_PATHS[1])], privileged=True)
        for relative, source, mode in (
            (OVERLAY_PATHS[2], overlay / "usr-local-sbin/h102-grow-rootfs", "0755"),
            (OVERLAY_PATHS[3], overlay / "systemd/units/h102-grow-rootfs.service", "0644"),
            (OVERLAY_PATHS[8], overlay / "systemd/units/h102-headless-boot.service", "0644"),
        ):
            self.run(["install", "-D", "-o", "root", "-g", "root", "-m", mode, str(source), str(root / relative)], privileged=True)
        for relative, source in DESKTOP_OVERLAYS:
            self.run(["install", "-D", "-o", "root", "-g", "root", "-m", "0644",
                      str(self.project / source), str(root / relative)], privileged=True)
        marker = self.evidence / "compact-image"
        marker.write_text(f"source_sha256={SOURCE_SHA}\nroot_blocks={ROOT_BLOCKS}\n")
        self.run(["install", "-D", "-m", "0644", "-o", "root", "-g", "root", str(marker), str(root / OVERLAY_PATHS[5])], privileged=True)
        self.run(["systemctl", f"--root={root}", "enable", "h102-grow-rootfs.service"], privileged=True)
        self.run(["systemctl", f"--root={root}", "enable", "h102-headless-boot.service"], privileged=True)

    def verify_root(self, source_root: Path, root: Path) -> None:
        """Compare full trees and first-boot conditions; verify allowed replacements separately."""
        excludes = ["--exclude=/" + name for name in OVERLAY_PATHS] + ["--exclude=/etc/h102/"]
        changes = self.run(["rsync", "-aHAXnci", "--numeric-ids", "--delete", "--omit-dir-times", *excludes,
                            str(source_root) + "/", str(root) + "/"], privileged=True)
        (self.evidence / "root-content-differences.txt").write_text(changes)
        # rsync reports new parent directories even when their declared leaves
        # are excluded. Only absent desktop parents may be created here.
        allowed = {"cannot delete non-empty directory: " + str(Path(name).parent)
                   for name, _ in DESKTOP_OVERLAYS
                   if not (source_root / Path(name).parent).exists()}
        unexpected = [line for line in changes.splitlines() if line not in allowed]
        if unexpected:
            raise RuntimeError(f"Unexpected root differences: {unexpected[:10]}")
        if sorted(path.name for path in (root / "etc/h102").iterdir()) != ["compact-image"]:
            raise RuntimeError("Unexpected compact configuration files")
        overlay = self.project / "overlays/h102"
        for relative, original in (
            (OVERLAY_PATHS[2], overlay / "usr-local-sbin/h102-grow-rootfs"),
            (OVERLAY_PATHS[3], overlay / "systemd/units/h102-grow-rootfs.service"),
            (OVERLAY_PATHS[5], self.evidence / "compact-image"),
            (OVERLAY_PATHS[8], overlay / "systemd/units/h102-headless-boot.service"),
        ):
            self.run(["cmp", str(original), str(root / relative)], privileged=True)
        for relative, source in DESKTOP_OVERLAYS:
            self.run(["cmp", str(self.project / source), str(root / relative)], privileged=True)
        for old in OVERLAY_PATHS[:2]:
            if (root / old).exists() or (root / old).is_symlink():
                raise RuntimeError("Legacy expansion hook remains")
        if os.readlink(root / OVERLAY_PATHS[4]) != "/etc/systemd/system/h102-grow-rootfs.service":
            raise RuntimeError("Growth service link incorrect")
        if os.readlink(root / OVERLAY_PATHS[9]) != "/etc/systemd/system/h102-headless-boot.service":
            raise RuntimeError("Headless completion service link incorrect")
        if (root / "etc/machine-id").stat().st_size != 0:
            raise RuntimeError("Shared image has a machine-id")
        for name in ("secret_key", "secret-key"):
            path = root / "var/lib/NetworkManager" / name
            self.run(["test", "!", "-e", str(path)], privileged=True)
            self.run(["test", "!", "-L", str(path)], privileged=True)
        host_keys = self.run(["find", str(root / "etc/ssh"), "-maxdepth", "1", "-name", "ssh_host_*", "-print"], privileged=True)
        if host_keys.strip():
            raise RuntimeError("Shared image has SSH host keys")
        passwd = (root / "etc/passwd").read_text()
        if not any(line.startswith("logicrf:") and line.split(":")[2] == "1000" for line in passwd.splitlines()):
            raise RuntimeError("logicrf UID 1000 missing")
        if any(line.startswith("analog:") for line in passwd.splitlines()):
            raise RuntimeError("analog account remains")
        for service, expected in (("NetworkManager", "enabled"), ("dhcpcd", "disabled"),
                                  ("h102-grow-rootfs", "enabled"), ("h102-headless-boot", "enabled")):
            actual = self.run(["systemctl", f"--root={root}", "is-enabled", service], privileged=True, accepted=(0, 1)).strip()
            if actual != expected:
                raise RuntimeError(f"Unexpected {service} state: {actual}")
        self.run(["grep", "-Fx", "PARTUUID=a22286d2-02  /               ext4    defaults,noatime  0       1", str(root / "etc/fstab")])

    def build(self) -> dict:
        """Copy, overlay, shrink and verify, releasing only resources created by this instance."""
        try:
            source_loop = self.attach(self.source, readonly=True)
            source_root = self.mount(source_loop + "p2", "source-root", readonly=True)
            self.run(["cp", "--sparse=always", "--reflink=auto", str(self.source), str(self.image)])
            output_loop = self.attach(self.image)
            root = self.mount(output_loop + "p2", "output-root", readonly=False)
            self.install_overlay(root)
            self.run(["sync", "-f", str(root)], privileged=True)
            self.unmount(root)
            self.run(["e2fsck", "-f", "-p", output_loop + "p2"], privileged=True, accepted=(0, 1))
            estimate = self.run(["resize2fs", "-P", output_loop + "p2"], privileged=True)
            (self.evidence / "resize-estimate.txt").write_text(estimate)
            if int(estimate.split()[-1]) >= ROOT_BLOCKS:
                raise RuntimeError("Estimated minimum exceeds 9 GiB target")
            self.run(["resize2fs", output_loop + "p2", str(ROOT_BLOCKS)], privileged=True)
            self.run(["e2fsck", "-f", "-n", output_loop + "p2"], privileged=True)
            self.detach(output_loop)
            original_mbr = verify_geometry(self.source, 57_228_288)
            self.run(["sfdisk", "--no-reread", "--no-tell-kernel", "--wipe", "never", "--wipe-partitions", "never", "-N", "2", str(self.image)],
                     input_text=f"size={ROOT_SECTORS}\n")
            new_mbr = verify_geometry(self.image, ROOT_SECTORS)
            if original_mbr[:462] != new_mbr[:462] or original_mbr[478:] != new_mbr[478:]:
                raise RuntimeError("MBR changed outside partition 2 entry")
            image_bytes = (ROOT_START + ROOT_SECTORS) * 512
            with self.image.open("r+b") as stream:
                stream.truncate(image_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            verify_geometry(self.image, ROOT_SECTORS)
            prefix_sha = digest(self.source, 512, ROOT_START * 512 - 512)
            if digest(self.image, 512, ROOT_START * 512 - 512) != prefix_sha:
                raise RuntimeError("Pre-root bytes (BOOT/p3/gaps) changed")
            output_loop = self.attach(self.image, readonly=True)
            self.run(["fsck.fat", "-v", "-n", output_loop + "p1"], privileged=True)
            self.run(["e2fsck", "-f", "-n", output_loop + "p2"], privileged=True)
            root = self.mount(output_loop + "p2", "output-root", readonly=True)
            self.verify_root(source_root, root)
            superblock = self.run(["dumpe2fs", "-h", output_loop + "p2"], privileged=True)
            (self.evidence / "compact-superblock.txt").write_text(superblock)
            fields = dict(line.split(":", 1) for line in superblock.splitlines() if ":" in line)
            if int(fields["Block count"].strip()) != ROOT_BLOCKS or int(fields["Block size"].strip()) != 4096:
                raise RuntimeError("Unexpected compact filesystem size")
            layout = self.run(["sfdisk", "--dump", str(self.image)])
            (self.evidence / "compact-layout.sfdisk").write_text(layout)
            for destination in list(reversed(self.mounts)):
                self.unmount(destination)
            for loop in list(reversed(self.loops)):
                self.detach(loop)
            image_sha = digest(self.image)
            # The full pinned source was hashed before copying. Repeat after all
            # mutation/verification operations to prove the source was preserved.
            if digest(self.source) != SOURCE_SHA:
                raise RuntimeError("Pinned source changed during build")
            result = {"schema_version": 1, "status": "offline_candidate_not_board_qualified",
                      "image": {"filename": IMAGE_NAME, "bytes": image_bytes, "sha256": image_sha},
                      "inputs": {"source_image_sha256": SOURCE_SHA, "rtl_bit_sha256": "f8ce7183d3a74e464c63ddcecd95321fe29068ffbcac9ac02c09a3940e74c45b"},
                      "offline_checks": {"fat_ext4": "passed", "root_content_preserved_except_declared_overlay": True,
                                         "pre_root_bytes_sha256": prefix_sha, "mbr_identity_and_non_root_entries_unchanged": True,
                                         "source_sha256_unchanged": True, "first_boot_identity_prepared": True,
                                         "desktop_opt_in_default_absent": True,
                                         "root_bytes": ROOT_BLOCKS * 4096, "old_grow_hook_removed": True},
                      "desktop_policy": {"marker": "/etc/h102/enable-desktop", "default": "headless",
                                         "overlays": {name: digest(self.project / source)
                                                      for name, source in DESKTOP_OVERLAYS}},
                      "headless_boot_completion": {
                          "unit": "h102-headless-boot.service", "enabled": True,
                          "unit_sha256": digest(self.project / "overlays/h102/systemd/units/h102-headless-boot.service"),
                          "cold_boot_qualified": False},
                      "board_checks": {"physical_card_written": False, "cold_boot_and_online_root_growth": False,
                                       "uart_network_iio_usb": False}, "hardware_or_usb3_used": False}
            (self.output / "candidate.json").write_text(json.dumps(result, indent=2) + "\n")
            (self.output / (IMAGE_NAME + ".sha256")).write_text(f"{image_sha}  {IMAGE_NAME}\n")
            return result
        finally:
            # Cleanup errors must not hide owned, still-mounted resources.
            errors = []
            for destination in list(reversed(self.mounts)):
                try:
                    self.unmount(destination)
                except RuntimeError as error:
                    errors.append(str(error))
            for loop in list(reversed(self.loops)):
                try:
                    self.detach(loop)
                except RuntimeError as error:
                    errors.append(str(error))
            if errors:
                (self.evidence / "cleanup-errors.txt").write_text("\n".join(errors) + "\n")
                raise RuntimeError("Owned resources could not be cleaned; inspect cleanup-errors.txt")
            shutil.rmtree(self.temp)


def main() -> None:
    """Verify pinned inputs and a new output directory before building an offline candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if not source.is_file() or output.parent != project / "artifacts" or output.exists():
        parser.error("Require a regular source and a new direct child of this repository artifacts/")
    manifest = json.loads((project / "manifests/h102-product.json").read_text())
    if manifest["h102_offline_candidate"]["sha256"] != SOURCE_SHA:
        parser.error("Product source pin differs from compact-tool lineage")
    for name in ("cp", "e2fsck", "resize2fs", "sfdisk", "fsck.fat", "losetup", "mount", "umount", "udevadm", "rsync", "dumpe2fs", "sudo", "systemctl", "sync", "install"):
        if shutil.which(name) is None:
            parser.error(f"Missing host tool: {name}")
    subprocess.run(["sudo", "-n", "true"], check=True)
    if source.stat().st_size != SOURCE_BYTES or digest(source) != SOURCE_SHA:
        parser.error("Source length/SHA-256 does not match the pinned NM candidate")
    verify_geometry(source, 57_228_288)
    if shutil.disk_usage(project / "artifacts").free < 40 * 1024**3:
        parser.error("Need at least 40 GiB free for staging and verification")
    output.mkdir()
    (output / "evidence").mkdir()
    builder = Builder(source, output, project)
    try:
        print(json.dumps(builder.build(), indent=2), flush=True)
    except Exception as error:
        (output / "evidence/failure.txt").write_text(str(error) + "\n")
        raise


if __name__ == "__main__":
    main()

# End of file: compact_h102_image.py
# Contact: info@logicrf.com
# Website: https://www.logicrf.com
