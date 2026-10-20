# Hawk H102 downloads and setup order

Use the matching components below when provisioning a new H102. All linked repositories and releases currently require private repository access. The base image and device services are separate downloads.

## Downloads

| Component | Version | Download and purpose |
|---|---|---|
| Bootable SD image | H102 Kuiper 1.2.0 / 2024.1 | [Image release](https://github.com/logicrf/hawk-h102-linux/releases/tag/h102-kuiper-1.2.0-image); download all three parts and reassemble the XZ |
| Device services | 1.0.0-en-r1 | [Service release](https://github.com/logicrf/hawk-h102-linux/releases/tag/h102-board-services-1.0.0-en-r1); API36/cap3 plus network-performance 1.0.0 |
| Standalone IIO GUI | 0.8.0-source-en-r2 | [GUI source release](https://github.com/logicrf/hawk-h102-iio-gui/releases/tag/v0.8.0-source-en-r2); bilingual desktop configuration, plots, IQ recording and supported TX |
| GNU Radio module | gr-logicrf 1.2.2rc2 English source | [Module source release](https://github.com/logicrf/gr-logicrf/releases/tag/v1.2.2-rc2); native GRC examples, FM, IQ and time-domain applications |

Exact filenames, sizes and SHA-256 values are in [the delivery manifest](../manifests/h102-customer-delivery-20261020.json). Source-delivery versions do not identify new firmware or extend earlier hardware tests. The Linux repository is an integration toolkit, not a complete standalone corresponding-source set for every system/vendor component.

## 1. Prepare a new SD card

Follow [image download and reassembly](IMAGE-DOWNLOAD.md), then use the [current deployment tools](https://github.com/logicrf/hawk-h102-linux/releases/tag/h102-deployment-tools-1.2.0-en-r2) and [SD deployment guide](DEPLOYMENT.md). The writer streams XZ input, verifies the full compressed and expanded hashes and performs complete direct card readback. A source ZIP is not an SD image. Select and inspect the exact whole-card device before any write.

Boot the H102 normally, allow initial identity creation/root expansion to finish, find its DHCP address and complete the documented first-boot checks. Each device needs independent identity; do not clone another unit's installation transactions or generated host keys.

## 2. Install matching device services once

Use [the device-service guide](BOARD-SERVICES.md). Verify the bundle, stage its unchanged firmware payloads in a new root-controlled directory on the H102, install the API36/cap3 package, reboot normally and check actual activation before installing the network add-on.

The base image alone does not include these later IP-only services. The staged-files receipt is not an installation receipt. Keep per-device backup/activation records. The optional 4 MSPS / 2 MHz shared-LO boot profile requires an explicit administrator choice.

## 3. Install the host application

For the IIO GUI, follow [GUI installation](https://github.com/logicrf/hawk-h102-iio-gui/blob/v0.8.0-source-en-r2/docs/INSTALL.md). English is the first-launch default; Simplified Chinese and saved user preferences are retained.

For GNU Radio, install the documented GNU Radio 3.10.12.0 environment and follow [module installation](https://github.com/logicrf/gr-logicrf/blob/v1.2.2-rc2/docs/INSTALL.md). Open the supplied editable `.grc` examples in Companion.

After administrator setup, ordinary applications connect using the H102 IP only. Linux credentials are not requested for ordinary device-control sessions. Use 8 MSPS / 4 MHz and RX1 as a practical initial GUI receive configuration, then verify actual configuration readback.

## 4. Check the new device

Confirm the current boot, actual API/capability, profile/sample-rate/bandwidth readback and a bounded receive window on that unit. Ethernet IQ16 admission uses a 64 MB/s aggregate budget; a displayed spectrum does not prove loss-free recording. Follow the application's recording result and keep partial files on failure.

USB additionally requires the matching FT601 host service and applicable driver/library terms. Those host components are not bundled in the device-service ZIP. RF transmission requires an appropriate load/attenuated connection and explicit TX operation.

## Licensing and support scope

Each component retains its own terms. The gr-logicrf GPL grant does not automatically relicense the standalone GUI, firmware, RTL or vendor SDK. Original qualified firmware archive bytes are preserved; English source/documentation updates are managed separately.

This delivery adds source packaging, exact archive pairing, English installation guidance and offline staging checks. It does not add a new per-device installation, SD cold-boot, USB/RF, all-profile or arbitrary-duration qualification. Keep the existing release's precise hardware limits and perform the new unit's checks before application use.

For component-specific source availability and remaining source-delivery review,
read [Source availability](SOURCE-AVAILABILITY.md).
