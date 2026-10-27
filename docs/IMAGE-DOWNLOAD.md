# H102 Kuiper 1.2.1 SD image

This is the existing released LogicRF Hawk H102 Kuiper 1.2.1 / 2024.1 image, split for GitHub download limits. Reassembly restores the original compressed file exactly; the accepted rc2 image bytes are preserved.

## Download

From this private release, download **all three** `.img.xz.part01`, `.part02` and `.part03` files, plus `image-parts.json`, `h102_reassemble_image.py`, `SHA256SUMS` and `H102-Deployment-Tools-1.2.1-en.zip`. Access requires a GitHub account with permission to this private repository.

GitHub's automatic "Source code (zip/tar.gz)" downloads contain source, **not the SD image**. A part alone is also not a bootable image.

## Reassemble on the download computer

Keep the parts, manifest and Python tool in one directory. Use Python 3.10 or newer and a local filesystem supporting hard links (for example ext4 or NTFS). Allow at least 2.76 GB free for the assembled compressed file in addition to the downloaded parts.

```bash
python3 h102_reassemble_image.py --verify-only
python3 h102_reassemble_image.py --output LogicRF-Hawk-H102-Kuiper-1.2.1-2024.1.img.xz
```

On Windows use `py -3` instead of `python3`. Do not use PowerShell `Get-Content` to concatenate binary image parts. Windows execution of this packaging tool has not been newly validated in this release update; the actual full-size merge verification was performed on Linux.

The tool verifies every part's size/hash and the complete image before publishing the final filename. It never overwrites an existing image. A failed `.partial` file is unverified and must not be written to a card.

| File | Bytes | SHA-256 |
|---|---:|---|
| Reassembled `.img.xz` | 2,760,770,292 | `31d554358ab80111c8b9244a93261e184c0766a13680fb860199a4154df5aea5` |
| Expanded `.img` | 11,823,742,976 | `ce03f2d9cc496842548996bb18e14e5c2e4bfea10842dbc701bf7fb9833eec92` |

## Write the card and boot

Extract the deployment-tool ZIP and follow `docs/DEPLOYMENT.md`. The Linux tool accepts the verified `.img.xz` directly, verifies input completely, exclusively writes the explicitly selected whole card, then performs full O_DIRECT readback and safe ejection. No card is selected automatically. A 32-GB SD card is suitable.

With the H102 powered off, insert the written card, connect Ethernet to a DHCP network and boot. Allow first-boot identity generation and root expansion to finish. Check each new device's unique identity, services and a bounded receive test. UART0 is 115200 baud, 8N1, no flow control.

## Version and scope

The image uses API 68.21.6, firmware 1.0.2, stream 0.7.22.0 and the shared-LO-capable 1.2.1 kernel. It contains 29 logical sample-rate/bandwidth choices in two LO modes, 58 packages. Internal build metadata may still show `1.2.1-rc2` because the released image was promoted byte-for-byte.

IP-only device control and network affinity are already included. Use GUI 0.8.1 or gr-logicrf 1.2.3. Do not install the older 1.2.0 service add-on over this image or edit firmware/helper locks to force a mismatch.

The exact first-unit cold/warm boot, physical-card readback, identity, representative IIO/USB and Linux ADI Oscilloscope scope is recorded in [system compatibility](PANEL-SYSTEM.md). It does not establish unlimited losslessness, all-profile endurance, a second-unit qualification or absolute RF/UTC performance.

The image is based on the pinned 18 March 2025 ADI Kuiper Full userspace input. Upstream and vendor components retain their own licenses and notices. This release remains private; it is not a blanket public redistribution authorization.
