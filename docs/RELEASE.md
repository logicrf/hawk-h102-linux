# H102 Kuiper 1.2.0 release information

Released 15 October 2026. This is the LogicRF H102-specific derivative of ADI Kuiper, based on the 18 March 2025 ADI Kuiper Full image / 2023_R2 Patch1. ADI and upstream components retain their attribution and licenses.

| Item | Value |
|---|---|
| Compressed image | `LogicRF-Hawk-H102-Kuiper-1.2.0-2024.1.img.xz` |
| Compressed size | 2,759,144,392 bytes |
| Compressed SHA-256 | `5a09380de3cea3219cc2ffb2cff2a2281e03b5e1c2fee2070c4e77aa9cd170a7` |
| Expanded image size | 11,823,742,976 bytes |
| Expanded SHA-256 | `22b21bf4deb2a66b7bfc2c57cca34797e475252c7d6c7a14b28a981c536f978d` |
| SDK/API | 1.0.0 / 68.21.6 |
| Transceiver firmware/stream | 1.0.2 / 0.7.22.0 |
| Kernel | `6.6.0-h102-sdk1-candidate-calfix1-regbounds1-sharedlo1` |
| Matching RTL tag | `h102-kuiper-1.2.0-rtl` |
| Built-in profiles | 29 combinations in independent/shared LO modes, 58 packages |

The release promotes the verified RC2 image byte-for-byte. Its internal build metadata may still show `1.2.0-rc2`; this does not mean a different image was supplied.

The release includes calibration power-state fixes, bounded ADC register access, shared-LO joint tuning and initialization fixes. The original RTL/data-frame format remains part of the matching release. Later device-control and GNU Radio performance add-ons are versioned separately; obtain the matching add-on set for those applications.

Two H102 units completed the recorded release-specific checks. Test windows cover boot/setup, representative Qt operation, finite IQ recording, USB digital paths and recovery; they do not establish unlimited-duration losslessness for all hosts/profiles, calibrated absolute RF power/UTC or dual-channel phase coherence. New units still need first-boot identity/network checks and a receive test.

This toolkit includes deployment and integration source; images and complete corresponding-source/vendor inputs are supplied separately. See SOURCE-BASE.json for exact provenance and docs/BUILD.md for reconstruction requirements. This English source update produces no new image, RTL, kernel or hardware qualification.
