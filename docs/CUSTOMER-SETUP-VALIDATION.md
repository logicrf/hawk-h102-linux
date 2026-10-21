# New-card setup validation: 21 October 2026

This check exercised the documented SD, device-service and host-application setup on one H102 using a new 64 GB card. The original Kuiper 1.2.0 image and released service archives were unchanged.

## Matched versions

| Component | Version |
|---|---|
| SD image | H102 Kuiper 1.2.0 / 2024.1 |
| SD deployment tools | 1.2.0-en-r2 |
| Device services | 1.0.0-en-r1: API36, actual capability 3, 108 pinned SDK files and network-performance 1.0.0 |
| IIO GUI | 0.8.0 source r2, `15d2b475` |
| GNU Radio module | 1.2.2rc2, `304400e0` |

The [validation receipt](../manifests/h102-customer-setup-validation-20261021.json) provides exact hashes, sample counts and scope. Administrator installation used a host key checked through the physical UART. Ordinary GUI/GNU Radio operations used the device IP only.

## Results

| Check | Observed result |
|---|---|
| SD write | Complete input hashes, 11,823,742,976 bytes written and full same-descriptor O_DIRECT readback passed. Automatic ejection briefly reported busy; a fresh idle check and separate safe ejection passed. No second write was needed. |
| New-card startup | New identity, 587 files, four links, 58 profile packages, the default idle 40 MSPS / 20 MHz configuration, root expansion and Gigabit networking passed. The earliest initial power-on UART output was not captured; login and actual startup state were verified. |
| Device services | Verification/staging with supplied Python 3.9.2, installation, normal reboot, actual capability 3, pinned SDK/API activation and network settings passed. The service reboot UART was captured. |
| GUI reception/recording | Dual RX at 4 MSPS / 2 MHz shared LO, five-second requested recording: device overflow guards, receive/file counts and full hashes passed. English/Chinese switching and both spectrum/waterfall views worked during actual reception. |
| Interactive GRC example | Single RX at 4 MSPS: start, pause, tune, resume, time/spectrum plots and independent release passed. |
| GRC recording | Dual RX at 8 MSPS / 4 MHz shared LO: exactly 16,000,000 samples and 128,000,000 cf32 bytes per channel; device guards, native/observer/file counts and full hashes passed. |
| GRC replay | Both recorded channels separately replayed all 16,000,000 samples with file/metadata checks. No device connection or RF transmission was used for replay. |
| Final state | Four DMA buffers, TX and DDS off; no H102 ownership locks or failed services. |

Qt windows rendered actual network IQ offscreen. This does not qualify every desktop graphics configuration. The GUI channels have separate complete-block endpoints; synchronized start/end and phase coherence were not established. IIO records relative sample time. An empty IIO H1MI index is expected; native USB frame indices and absolute ADC UTC are not fabricated.

## Timing observations

| Operation | Seconds |
|---|---:|
| GUI connection | 4.53 |
| GUI cold profile change, 40 to 4 MSPS | 27.12 |
| GUI same-profile frequency control/readback | 0.29 |
| GUI first plotted IQ during strict recording | 2.87 |
| GRC first IQ with the 4 MSPS profile already active | 5.69 |
| GRC same-profile tune to next-generation IQ | 2.22 |
| GRC pause and data drain | 0.14 |
| GRC resume to first IQ | 1.53 |
| GRC cold change from 4 to 8 MSPS, including first IQ | 25.81 |

Cold profile programming and warm operations have different costs. These observations apply to this test host, device and profiles; they are not universal latency guarantees. Ethernet dual 8 MSPS uses the 64 MB/s IQ16 admission budget; cf32 recording requires 128 MB/s of host storage throughput.

## Source inventory and remaining scope

The new card supplied a [2,202-row installed package/source-version mapping](../manifests/h102-kuiper-1.2.0-installed-packages.tsv) and a [2,191-entry copyright path/hash index](../manifests/h102-kuiper-1.2.0-copyright-index.json). These describe the installed rootfs after the service add-ons, which did not install packages. They do not include complete source archives, all manually installed software or a full license determination. See [source availability](SOURCE-AVAILABILITY.md) for the open kernel, BOOT and vendor source-delivery items.

This campaign did not transmit RF, transfer USB data, repeat the full 58-profile streaming matrix, qualify another board or add long-duration/calibrated RF/UTC evidence. Two browser download checks also remain open: the three large image parts and the deployment-tools r2 ZIP were blocked by the browser. Server checksums and local verified files do not replace an actual download/readback check. Repository access remains private.

Use [the setup guide](DELIVERY.md) for the installation sequence and repeat the new unit's identity and bounded receive checks before use.
