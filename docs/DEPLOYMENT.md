# Deploy the released image to a new H102

For one-command writing and DHCP-first/static fallback setup, start with [SD quick write](SD-QUICK-WRITE.md). The detailed inspection and SSH checks below are administrator tools; normal GUI and GNU Radio use only the device IP. Existing cards can use the [UART IPv4 setup](https://docs.logicrf.com/en/hawk-h102/system#static-ipv4).

Use a Linux host with Python 3.10+, util-linux (`lsblk`, `blockdev`), udisks2 (`udisksctl`), e2fsprogs (`debugfs`, `e2fsck`), kernel loop support and administrator access for writing. Use a card large enough for the 11,823,742,976-byte image. A 32-GB card is suitable; the first boot expands the root filesystem.

## 1. Obtain and verify the image

Obtain `LogicRF-Hawk-H102-Kuiper-1.2.1-2024.1.img.xz` through the product delivery channel. Compare the size and SHA-256 with [release information](RELEASE.md) and `manifests/h102-deployment-1.2.1.json`. Do not use a Git LFS pointer or source ZIP.

The writer streams compressed input and needs no separate expanded IMG file, but verifies both complete compressed and expanded hashes before writing. A complete direct readback follows writing, so the operation reads the image/card more than once.

## 2. Select the card explicitly

```bash
python3 scripts/h102_sd_deploy.py list
export SD_DEVICE=/dev/sdX
python3 scripts/h102_sd_deploy.py inspect --device "$SD_DEVICE"
```

Replace `/dev/sdX` with the actual **whole card device**, not a partition. Inspect the model, serial/path, capacity, mounts and blockers. Unmount its partitions using the host's normal tools. The writer does not unmount automatically or bypass a busy device. `inspect` returns a confirmation code bound to the current kernel disk identity; inspect again after reinsertion.

## 3. Write, verify and eject

This command overwrites the selected card completely. Replace `CURRENT_INSPECT_CODE` with the current inspect result and choose a report path that does not exist:

```bash
sudo python3 scripts/h102_sd_deploy.py write \
  --device "$SD_DEVICE" \
  --image /path/to/LogicRF-Hawk-H102-Kuiper-1.2.1-2024.1.img.xz \
  --confirm CURRENT_INSPECT_CODE \
  --report /path/to/new-card-write.json
```

The tool holds one exclusive block-device FD through write, fsync, full O_DIRECT readback and network customization. By default it installs DHCP-first startup with fallback to 10.168.1.199/24. It checks all five network files and ext4 consistency before ejection. A failed stage is reported explicitly; it does not use cached readback or retry writing automatically. Follow the final ejection result before removing the card. Use `--network dhcp` for DHCP only or `--network static --address IP/PREFIX` for a manual address; optional `--gateway` must be another host in that subnet, and `--dns` accepts up to three comma-separated IPv4 addresses.

## 4. First boot and basic checks

With the H102 powered off, install the card and connect Ethernet. UART0 uses 115200 baud, 8N1, no flow control. Power on and allow identity generation, root expansion and initialization to finish. Use the actual DHCP address when a lease is available. Otherwise the default writer's setup falls back to 10.168.1.199/24 after the DHCP transaction timeout; the computer must have a different address in that subnet. Provision different fallback addresses for multiple H102 units.

Ordinary matching GUI/GNU Radio control sessions use only the device IP with the control service already included in this image. Administrator first-boot checks use an existing trusted SSH connection or run locally on the board:

```bash
python3 scripts/h102_check_new_board.py --host H102_IP \
  --report /path/to/new-board-check.json
```

The host SSH key must already be trusted. Use `--identity-file /path/to/existing/key` if needed. This is an administrator check, not authentication required by the ordinary IIO/API data path. See `--help` for local-board and comparison options.

Check independent machine/MAC/SSH identities, matching kernel/boot assets, 58 profile packages, services, expansion and network state. Basic PASS does not prove IQ continuity or RF performance. Complete a bounded receive test in a bandwidth-admitted configuration before using a newly provisioned unit in an application.

## Validation scope

The exact 1.2.1 image and physical-card writer passed complete write/direct readback and first-unit cold/warm boot, identity persistence and representative data checks. See the [acceptance scope](PANEL-SYSTEM.md). Earlier two-board checks apply to their original 1.2.0 inputs; they do not qualify an untested new unit. Run basic identity/service checks and bounded, bandwidth-admitted receive checks on every new H102.

Tools 0.3.0 additionally passed default-auto single-command card deployment, fresh-card cold/warm boot, identity persistence and a ten-second dual-RX GUI recording at 4 MSPS. The earlier DHCP-failure test rejected fresh offers on the board while preserving the laboratory DHCP server; physical server absence and deliberate address conflicts were not newly tested. No new image, RTL, USB, full-profile or RF performance qualification is implied. The original 1.2.1 image retains DHCP-only settings when written without these tools.

## Hosts using AppImage/FUSE

The deployment tools handle a process descriptor that FUSE exposes to its
owner but denies to root. A bounded read-only child drops privileges to that owner
to classify it. Actual target block descriptors, unreadable descriptors and changed
descriptors still refuse the write. No mount permissions are changed. A failure
before `destructive_write_started_at` means the writer has not overwritten the card.
