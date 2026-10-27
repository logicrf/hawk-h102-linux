# Hawk H102 downloads and setup order

Use the integrated Kuiper 1.2.1 image with GUI 0.8.1 or gr-logicrf 1.2.3. The image already includes IP-only device control and network affinity. Do not install the older 1.2.0 board-service add-on over it. The repositories and downloads currently require private GitHub access. A source ZIP is not a bootable SD image.

| Component | Matching version | Download |
|---|---|---|
| Bootable SD image | Kuiper 1.2.1 / 2024.1 | [Image release](https://github.com/logicrf/hawk-h102-linux/releases/tag/h102-kuiper-1.2.1-image); all three parts are required |
| SD deployment tools | 1.2.1 English | Included with the image release; fixed manifests, exact card selection, complete direct readback and first-boot checks |
| IIO GUI | 0.8.1 | [GUI source](https://github.com/logicrf/hawk-h102-iio-gui/releases/tag/v0.8.1) |
| GNU Radio module | gr-logicrf 1.2.3 | [Module source](https://github.com/logicrf/gr-logicrf/releases/tag/v1.2.3) |
| Optional USB host tools | 1.0.0-r2 | [USB host setup](https://github.com/logicrf/gr-logicrf/releases/tag/h102-usb-host-tools-1.0.0-r2) |

## Prepare the card

Follow [download and reassembly](IMAGE-DOWNLOAD.md), then [SD deployment](DEPLOYMENT.md). Download all parts and verify the compressed image. The Linux writer accepts XZ directly, checks both complete input hashes, holds an exclusive FD on the explicitly inspected whole card, performs complete O_DIRECT readback and safely ejects. A 32-GB card is suitable. Writing overwrites that card.

With the H102 powered off, insert the card and connect Ethernet to DHCP. Keep the factory SD-boot setting. Allow first-boot identity creation and filesystem expansion to finish, including any automatic reboot. Find the device's actual IP and run the documented administrator first-boot checks. Each new H102 needs independent machine/MAC/SSH identities and its own bounded receive check.

## Install the host application

Follow [GUI installation](https://github.com/logicrf/hawk-h102-iio-gui/blob/v0.8.1/docs/INSTALL.md) or [GNU Radio installation](https://github.com/logicrf/gr-logicrf/blob/v1.2.3/docs/INSTALL.md). The GUI defaults to English and retains Simplified Chinese and saved preferences. GNU Radio uses the supplied editable `.grc` examples, GNU Radio 3.10.12.0 and QtGUI.

Ordinary application sessions use only the device IP; no Linux username or password is requested. Administrator installation and diagnostic SSH are separate operations. Begin with an admitted low-rate receive configuration, such as 4 MSPS / 2 MHz, and verify actual profile, carriers, gain and bandwidth before capture. Stop and disconnect one application before opening another.

## Check data integrity

The Ethernet IQ16 aggregate admission budget is 64 MB/s. Displaying a spectrum does not establish loss-free recording. Use the application's recording result, complete file checksums and preserved partial files on failure. USB additionally requires the matching FT601 host service and separately obtained vendor inputs. RF TX requires the intended load/attenuated connection and explicit TX operation.

The exact new image passed first-unit card/cold/warm/identity checks, representative IIO dual RX and digital USB dual TX, and Linux ADI Oscilloscope control/display/reconnect. All defaults were restored with RF off. See [precise scope](PANEL-SYSTEM.md). This is not an all-host/all-profile endurance or absolute RF/UTC guarantee.

## Previous installations and source materials

The previous 1.2.0 image and [separately installed services](BOARD-SERVICES.md) keep their original versions and qualification. Back up a previous working card before replacing it; do not mix helper/firmware locks. Complete-system corresponding source is still incomplete: see [source availability](SOURCE-AVAILABILITY.md), [boot rebuild](BOOT-REBUILD.md), [rootfs source materials](ROOTFS-SOURCES.md) and [offline source export](SOURCE-MATERIALS.md). Each component retains its own license; the module's GPL does not relicense the separate GUI, RTL or vendor SDK.
