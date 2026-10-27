# Kuiper 1.2.1 integrated system image

Kuiper 1.2.1 includes the S0/S1 panel indicators, IP-only device control, the matching SDK runtime and network affinity service. Use IIO GUI 0.8.1 or gr-logicrf 1.2.3. A newly written card does not require the older separately installed board-service add-on.

The stable image preserves the accepted 1.2.1-rc2 bytes. Its internal metadata still identifies rc2; this is intentional. Use the exact manifest rather than editing the image to change that label. The pinned original integration recipe is `e9dfd5ee04f51bc41abc44784252dcca92f06b16`; a later source checkout is not a byte-identical reconstruction of those original inputs.

| Component | Matching version |
|---|---|
| System | Kuiper 1.2.1 / 2024.1; internal build 1.2.1-rc2 |
| RTL | 1.2.1; compiled design 134a61f; BIT d6a2412c... |
| ADRV9002 | API 68.21.6, firmware 1.0.2, stream 0.7.22.0 |
| Profiles | 29 sample-rate/bandwidth choices; 58 packages across two LO modes |
| Device API | 0.1.0-ip36-panel1, included |
| Desktop applications | IIO GUI 0.8.1; gr-logicrf 1.2.3 / GNU Radio 3.10.12.0 |

S0 indicates the FPGA heartbeat at approximately 1 Hz. S1 flashes at approximately 4 Hz during host IQ activity and is off when idle. These indicators do not establish Linux readiness, RF power, UTC validity or recording integrity.

The exact image passed complete physical-card write/direct readback, cold and warm boot, independent persistent identity, 618 file/five link/three private-directory checks, representative IIO dual RX and digital USB dual TX, and the Linux ADI IIO Oscilloscope control/display/reconnect checks. All default settings were restored with RF TX off. See the [scoped acceptance receipt](receipts/20261027-1.2.1-exact-image-acceptance.json). This does not extend qualification to a second unit, a new full-profile endurance matrix, RF metrology, absolute UTC or Windows Oscilloscope.

Use [downloads and setup order](DELIVERY.md), [SD deployment](DEPLOYMENT.md) and the fixed `manifests/h102-deployment-1.2.1.json`. The source distribution remains an integration toolkit, not the complete corresponding source for every system component; see [source availability](SOURCE-AVAILABILITY.md).
