# Sample profiles and RF configuration

H102 1.2.0 includes 29 sample-rate/bandwidth combinations in two LO modes, for a total of 58 profile packages. Choose an installed profile on the H102; Windows tools are not needed for routine operation.

| Sample rate (MSPS) | Available RF bandwidths (MHz) |
|---:|---|
| 0.192 | 0.05, 0.1 |
| 0.768 | 0.2 |
| 1.536 | 0.5, 1 |
| 2 | 0.25, 0.5, 1 |
| 4 | 0.5, 1, 2 |
| 8 | 1, 2, 4 |
| 10 | 5 |
| 16 | 2, 4, 8 |
| 20 | 5, 10 |
| 23.04 | 15 |
| 30.72 | 15.36, 20 |
| 40 | 10, 20, 30 |
| 61.44 | 20, 30, 40 |

Independent mode uses RX1/RX2 on LO2 and TX1/TX2 on LO1. Shared mode uses LO2 for all four channels, so RX/TX center frequencies must agree. Shared-mode IDs end in `-common`. Decimal values use `p`, for example `0p192msps-0p05mhz`.

Center frequency is a runtime RF setting, separate from the profile's sample rate and filters. Changing center frequency within supported limits does not require regenerating a profile. Stop RX, TX, scans and recording before changing profiles. Applying a profile reinitializes the radio and can take more than 20 seconds.

## Select from an application

Use the profile selector in the H102 GUI or the matching GNU Radio example. Wait for completion before starting a new data session. The sample rate and DSP settings in a custom flowgraph must match the selected profile.

## Select through IIO

Replace `192.0.2.10` with the actual device IP:

```bash
iio_attr -u ip:192.0.2.10 -d h102-profile-control available
iio_attr -u ip:192.0.2.10 -d h102-profile-control select 20msps-10mhz
iio_attr -u ip:192.0.2.10 -d h102-profile-control request_id
iio_attr -u ip:192.0.2.10 -d h102-profile-control status
iio_attr -u ip:192.0.2.10 -d h102-profile-control active_info
```

A successful `select` write queues the request; it does not mean the radio has finished applying it. Track the returned request ID, wait for `applied`, `rolled_back` or `rejected`, then check `active_info`. While applying, active attributes may report ENODATA. A busy device rejects competing requests.

## Administrator CLI

Run these on the H102 when it is idle:

```bash
sudo h102-config-sdk1 list
sudo h102-config-sdk1 status
sudo h102-config-sdk1 validate 20msps-10mhz
sudo h102-config-sdk1 apply 20msps-10mhz
sudo h102-config-sdk1 status
```

Use `20msps-10mhz-common` for shared LO. `sudo h102-config-sdk1 restore` returns to the previous managed configuration. Runtime selection does not change the boot default.

A profile being installed does not imply every RX/TX combination fits a transport. IQ16 uses four bytes per complex sample; apply the host application's bandwidth checks. Do not edit package checksums or rename independent packages to create shared-mode profiles.
