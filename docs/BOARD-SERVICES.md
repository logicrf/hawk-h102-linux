# Install matching H102 device services

Use this administrator package after deploying the exact LogicRF Hawk H102 Kuiper 1.2.0 SD image. It combines the existing API36/cap3 and network-performance 1.0.0 archives with an English verification/staging tool and installation guide.

## Matching components

| Component | Required delivery |
|---|---|
| Base image | Kuiper 1.2.0 / 2024.1, compressed SHA-256 `5a09380de3cea3219cc2ffb2cff2a2281e03b5e1c2fee2070c4e77aa9cd170a7` |
| Kernel | `6.6.0-h102-sdk1-candidate-calfix1-regbounds1-sharedlo1` |
| Device services | Hot-metadata add-on r5, API `0.1.0-ip36`, 108 pinned SDK files and actual FPGA capability 3 |
| Network settings | network-performance 1.0.0 |
| Host applications | IIO GUI source packaging r2 `15d2b475` or gr-logicrf English source `304400e0`; install each application's documented dependencies |

Download `H102-Board-Services-1.0.0-en-r1.zip` and its checksum from the [device-service release](https://github.com/logicrf/hawk-h102-linux/releases/tag/h102-board-services-1.0.0-en-r1). Verify the full ZIP before extracting it into a new directory. The SD image is available separately; see [image download](IMAGE-DOWNLOAD.md).

The qualified firmware archives and their original installers are preserved byte-for-byte, including historical internal text. This English delivery changes the surrounding guide and verification tool. Do not translate these fixed payloads, edit service locks or regenerate them from translated source while claiming the same qualification. The package does not include FTDI D3XX libraries, a USB host broker or a new complete vendor SDK.

## Verify and prepare

Use the H102's supplied Python 3.9.2 for the board commands below. The unchanged
verification/staging tool passed an actual two-archive verification and 46-file
staging/readback on that interpreter. Host verification also passed on Python 3.10.
The desktop GUI's Python requirement applies to the PC, not the H102. This corrects
the 3.10+ statement in the original r1 ZIP guide; no tool or firmware bytes changed.

```bash
python3 h102_board_services.py verify --bundle .
sudo python3 h102_board_services.py stage --bundle . --output /root/h102-services-stage-1
```

Run the second command on the H102 itself. It creates a new directory, verifies every extracted file and prints the next administrator commands. The original installers require root-controlled paths; using sudo with a new directory under `/root` satisfies that requirement. Existing output directories and symlink paths are rejected.

`PASS_VERIFIED_NOT_INSTALLED` and `PASS_STAGED_NOT_INSTALLED` describe file checks only. This tool does not execute installers, connect over SSH, restart services, reboot, transmit RF or write SD cards.

## Install the device API

Stop all acquisition, recording and transmission and wait for device recovery. On the idle H102, run:

```bash
sudo python3 -B /root/h102-services-stage-1/h102-grc-hotmeta-addon-1-r5-20261018/install_hotmeta_addon.py \
  --package-sha256 03eada3019d48414fb15dd4f4ca1030a88fc2fcd7122d3fa094c49280e60c5cf
```

Continue only after `INSTALLED_REBOOT_REQUIRED`. Reboot normally and wait for the device-control service. Its startup check verifies the new boot, actual capability 3, idle state, matching SDK/API files and the device's own installation transaction. A bitstream file on disk is not proof that it was loaded. If activation fails, retain the transaction and backups and inspect the error before retrying.

## Install the network add-on

After the normal reboot and successful API startup:

```bash
sudo python3 -B /root/h102-services-stage-1/h102-network-performance-1.0.0/install_network_performance.py install
systemctl is-active h102-control-api.service h102-network-performance.service
sudo python3 -B /usr/local/lib/h102/network-performance/1.0.0/h102_network_performance.py status
```

Check that the actual settings report `gro_flush_timeout=500000` ns and `napi_defer_hard_irqs=2` applied. The service retains the original settings for the current boot.

To prepare 4 MSPS / 2 MHz with shared LO at boot for the GNU Radio examples, explicitly append `--prepare-grc-profile` to the first network installation command. Omit it to retain the base image's default profile. This moves cold programming into device startup; changing to another profile may still exceed 20 seconds.

## Use and validate each device

After administrator setup, ordinary GUI and GNU Radio users enter only the H102 IP. No Linux username or SSH password is needed for ordinary connections. Each new device still needs its own boot/version/configuration readback and a bounded acquisition check. Do not copy another device's machine identity or `/var/lib/h102` installation transactions.

Ethernet IQ16 admission uses an aggregate 64 MB/s budget. Profiles beyond that budget are not qualified for uninterrupted Ethernet capture. USB additionally requires the matching host-side FT601 service, driver terms and connection checks, supplied separately.

The original packaging checks covered archive integrity, pairing and offline staging. The [21 October new-card validation](CUSTOMER-SETUP-VALIDATION.md) adds one actual installation/reboot and representative GUI/GRC RX checks. RF, USB, other boards and long-duration qualification are outside that campaign.

## Roll back

Stop clients and confirm the device is idle. Run the same network package's `install_network_performance.py remove` first. Then use the same hot-metadata installer and exact package SHA with `--rollback`, retain its transaction and reboot normally when instructed. Do not delete backups or force installation over an unknown state.
