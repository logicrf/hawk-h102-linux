# LogicRF Hawk H102 Kuiper

**Current matching system: Kuiper 1.2.1 / 2024.1, IIO GUI 0.8.1 and gr-logicrf 1.2.3.** The integrated image includes panel indicators, IP-only device control and network affinity. Exact-card first-unit cold/warm boot, representative data checks and Linux ADI IIO Oscilloscope checks passed within the [recorded scope](docs/PANEL-SYSTEM.md). Use the matching release attachments and fixed hashes below; previous releases remain available for rollback.

[Retained-package provenance](docs/PACKAGE-PROVENANCE.md) documents the official signed binary records, recovered upstream packaging recipes and observed distribution differences. Five exact package-input records and 53 original Raspbian provenance records remain open; those source-provenance limits remain open.

The [rootfs source inventory](docs/ROOTFS-SOURCES.md) includes four recovered historical package sources: dpkg, Python 3.9, systemd and Qt Base. Five exact packaged source versions and original Raspbian production-input provenance for 53 Debian candidates remain unresolved. The complete-system-source limitations remain open.

H102-specific Linux integration, configuration and SD deployment tools for the LogicRF Hawk H102 SDR. The integrated operating-system baseline is **H102 Kuiper 1.2.1 / 2024.1**, using the 18 March 2025 ADI Kuiper Full userspace image and the pinned H102 kernel/boot inputs.

This repository provides English source and customer documentation. It contains the image integration recipes, H102 kernel patches and software IIO module, system overlays, radio-profile generation requests and tools, SD deployment utilities, optional device-control service source, and C++/Python IIO examples. It is maintained as a **private source distribution**, with component-specific licensing.

## Choose your task

| Task | Start here |
|---|---|
| Find matching downloads and provision a new H102 | [Downloads and setup order](docs/DELIVERY.md) |
| Write and verify an SD card with one shell command | [SD quick write](docs/SD-QUICK-WRITE.md) |
| Connect and use built-in configurations | [Getting started](docs/GETTING-STARTED.md), [configuration](docs/CONFIGURATION.md) |
| Generate additional ADRV9002 profiles | [Profile generation](docs/PROFILE-GENERATION.md) |
| Modify kernel or system-image integration | [Build inputs and workflow](docs/BUILD.md) |
| Install matching GUI/GNU Radio device services | [Device-service bundle](docs/BOARD-SERVICES.md) |
| Review the fixed device API source | [Device control](control-api/README.md) |
| Develop using libiio | [C++ and Python examples](examples/iio/README.md) |
| Check release source correspondence | [Kernel source review](docs/SOURCE-CORRESPONDENCE.md), [rebuild BOOT](docs/BOOT-REBUILD.md), [rootfs source materials](docs/ROOTFS-SOURCES.md), [manual component sources](docs/MANUAL-SOURCES.md), [export source materials](docs/SOURCE-MATERIALS.md) |
| Review the new-card setup check | [Validation on 21 October 2026](docs/CUSTOMER-SETUP-VALIDATION.md) |
| Review versions, hashes and support limits | [Release information](docs/RELEASE.md) |

## Verify this source package

On Linux with Python 3.10 or newer, from the repository root:

```bash
python3 scripts/check_distribution.py
python3 scripts/h102_sd_deploy.py --help
python3 scripts/h102_check_new_board.py --help
```

The source checker is offline: it verifies the included file set, hashes, English text, Python syntax and local Python import closure. It does not open a board or disk. Dependencies required for individual operations are listed in the build and deployment guides.

## Images and exact-version inputs

Download all three parts from the private [1.2.1 SD image release](https://github.com/logicrf/hawk-h102-linux/releases/tag/h102-kuiper-1.2.1-image), then follow [image download instructions](docs/IMAGE-DOWNLOAD.md) to restore and verify the actual `.img.xz`. Images, generated firmware/stream binaries, vendor SDKs, complete RTL and build outputs are not stored in this Git repository. A source archive is not a bootable image.

The historical image recipes retain their original source/asset checks. English translation changes source hashes: this export is **not** a new firmware release or a claim that translated files reproduce the released image byte-for-byte. Exact historical reconstruction requires the original pinned inputs listed in [build inputs](docs/BUILD.md). The source checkout alone is insufficient for a complete image build.

The 1.2.1 image includes the matching API/cap3 and network services. The older [device-service bundle](docs/BOARD-SERVICES.md) is a separate maintenance path for the previous 1.2.0 image. Do not overwrite a deployed stack with source files from this checkout without preparing and qualifying a matching installation.

[Licensing](LICENSE.md) · [Third-party notices](LICENSES/THIRD-PARTY-NOTICES.md) · [English branch maintenance](docs/MAINTAINING.md)

- [Source availability and component terms](docs/SOURCE-AVAILABILITY.md)

The private1.2.1 release is published. See the [publication receipt](docs/receipts/20261027-1.2.1-private-publication.json) for server-side asset verification and the remaining browser download-readback limitation. The image and frozen release tag remain unchanged.
