# Generating additional ADRV9002 profiles

Use built-in profiles whenever possible. Generating profiles is a development task; it is not required to change the RF center frequency or select an installed sample-rate/bandwidth combination.

## Matching tools

| Item | H102 1.2.0 requirement |
|---|---|
| ADI SDK | ADRV9001-SDK Evaluation Software 1.0.0 |
| API / ARM firmware / stream | 68.21.6 / 1.0.2 / 0.7.22.0 |
| Generator host | Windows 11 x64, .NET Framework 4.8, Windows PowerShell |
| Device template / reference clock | C0 / 300 MHz |
| Radio configuration | Dual RX/TX, FDD, RX1A/RX2A, equal sample rate/bandwidth across channels |
| SSI | LVDS, two lanes, DDR, 16-bit I/Q components |

The ADRV9001 SDK name also covers ADRV9002 devices. Obtain the SDK from [Analog Devices](https://www.analog.com/en/lp/001/transceiver-evaluation-software.html) under its own license. The pinned ZIP is `adrv9001-sdk-1pt0pt0.zip`, SHA-256 `5bd9ae08e9eedda15b48c643c01328557dcce9a52172dc52f4f32e180aad6653`.

H102 1.2.0 does not provide an on-device arbitrary-profile generator or a profile-generation web page. libiio controls devices/transfers IQ; it does not design filters. A generator targeting API 68.10.1 is not a substitute for this release's API 68.21.6 toolchain.

## Workflow

Use the matching LogicRF profile-development tools supplied separately. This documentation branch does not contain the generator scripts, ADI SDK or generated packages.

1. Verify the SDK ZIP and extract it to a clean directory. Do not mix SDK releases or copy individual DLLs between them.
2. Use the matching profile-generator scripts and pinned request catalogs from the H102 source/tool package.
3. Generate independent-LO and shared-LO catalogs separately. Each catalog contains 29 combinations; the combined 58-package catalog is not one generation request.
4. Check the generation receipt, per-profile success markers and output hashes. Keep failed outputs for diagnosis and use new output directories on retry.
5. Transfer the complete generated directories to Linux. Import with the matching H102 importer, which verifies API/firmware/stream versions, channel rates, analog settings, LO mapping, stream length and hashes.
6. Test the new package on an isolated development system: driver initialization, actual parameter readback, recovery and the intended data path. Add it to the approved catalogs and matching runtime before a new release.

Generator output includes `profile.json`, `stream.bin`, request/stream settings, success markers and `generation-receipt.json`. `stream.bin` configures the transceiver stream processor; it is not an FPGA bitstream. An imported package is not automatically approved for production use.

Do not infer analog corner settings from bandwidth alone. The released narrowband profiles contain validated analog settings that differ from a simple BW/2 calculation. Changes to SSI, reference clock, channel topology or native sample rates also require driver/RTL compatibility review.
