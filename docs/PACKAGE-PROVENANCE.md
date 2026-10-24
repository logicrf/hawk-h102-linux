# Retained Kuiper packages and their source inputs

This review describes the five open package records for Kuiper 1.2.0. It does not change the released image. Binary archives, upstream source, packaging recipes, original build inputs and component terms are tracked separately. The [inventory](../manifests/h102-package-provenance-review-1.2.0.json) records exact identities and verification limits.

## Verified archive records

The official Raspberry Pi bullseye binary index still lists BlueJ 5.0.3, Greenfoot 3.7.0, Scratch3 1.1.0, Chromium 126.0.6478.164-rpt1 and Widevine 4.10.2252.0+3. The InRelease signature was checked using the current public key obtained from the official HTTPS endpoint, followed by the Packages.gz digest and the size/SHA of the BlueJ, Greenfoot and Widevine packages. The key fingerprint is `CF8A1AF502A2AA2D763BAE7E82B129927FA3303E`. This verifies the current archive publisher; it does not establish the original image's key rotation or prove these files produced its installed files.

These binary packages were inspected without installation or execution and are not included in the source export. The large Scratch3 and Chromium binaries were not downloaded separately; index records are not full-file download verification.

## BlueJ and Greenfoot: recipes recovered, differences identified

The retained official upstream source ZIPs contain the unbundled Ant packaging targets, DEBIAN/control, postinst, postrm and launchers. The earlier statement that unbundled packaging inputs were missing was too broad: the recipes exist, while distribution changes and the complete original build-input chain remain unconfirmed.

| Compared material | Verified result | Limit |
|---|---|---|
| Four postinst/postrm scripts | Byte-identical to the exact official binaries | No scripts were executed |
| Main license texts | One BlueJ and two Greenfoot members match the source ZIPs | Not a complete dependency-license or source review |
| control | After substituting the exact Version, the binary additionally permits Java 17 | The upstream template permits only Java 11 |
| Launchers | The binaries add Java 17 JVM search paths | Original distribution patches were not recovered |

The [observed BlueJ patch](source-review/bluej-java17-observed.patch) and [observed Greenfoot patch](source-review/greenfoot-java17-observed.patch) reconstruct only these control and launcher differences. Both passed dry-run, application and output-byte comparison. They are not recovered original build patches. JARs were not rebuilt and binary reproducibility was not established, so both packages remain among the five open records.

BlueJ and Greenfoot include license files under paths such as `/usr/share/doc/BlueJ/` and `/usr/share/doc/Greenfoot/`, with names including LICENSE.txt. Their absence from the original 2,191-path copyright-only index does not mean the packages contain no license notices; that index is not a complete notice inventory.

## The other three packages

| Package | Available material | Still needed |
|---|---|---|
| Scratch3 1.1.0 | Exact official binary-index record; older source versions listed in the directory | Exact 1.1.0 source and packaging inputs; no substitution with 1.0.x |
| Chromium 126.0.6478.164-rpt1 | Exact official binary record, retained installed copyright material and the official RPi-Distro repository | Matching old chromium-browser source, patches and dependencies; the exact old tag was not found in the newer chromium repository |
| Widevine 4.10.2252.0+3 | Exact official index and binary SHA; package description identifies proprietary DRM | Exact +3 packaging inputs and applicable distribution terms; the listed +5 source is a different version |

Google's [Widevine overview](https://developers.google.com/widevine/drm/overview) states that use of its products or services requires a license agreement. Chromium's [Widevine notice](https://chromium.googlesource.com/chromium/src/third_party/+/master/widevine/LICENSE) identifies the CDM as non-open-source software. These upstream references do not replace authorization materials for this exact binary version. The inspected +3 package contains only the CDM library, manifest.json and changelog.gz as data members; no separate file named LICENSE or copyright was found. This does not establish whether a device owner holds other authorization. Proprietary-component terms remain separate from ordinary GPL source recovery.

## Original Raspbian inputs for the 53 Debian candidates

Exact-version references were queried for all 53 candidates in official Raspbian Dgit: 47 repositories were unavailable and six existed without the requested tag. This result is limited to those repositories and references; it does not establish that no source exists elsewhere. The latest directory listed by the old official snapshot index is 202112021208, and the inspected curl sourcearchive records predate the required security update. Neither is a historical signed index for the 2025 image. An official build-log entry for the exact curl version was located, but the body service returned an error; its source-input SHA was not recovered.

All 53 remain exact-version Debian candidates. Ten byte-identical mirror DSCs, a build-status page or a matching version do not replace original Raspbian production-input evidence. Complete-system corresponding source remains unfinished. This material review changes neither the image nor device behavior or hardware qualification.
