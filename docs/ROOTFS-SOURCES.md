# Kuiper 1.2.0 root filesystem source materials

This page records source-material availability for the released H102 image. The
installed system uses Raspbian bullseye and the Raspberry Pi archive. Use each
installed source name and version; a current Debian package is not a replacement
for a different Raspbian source version. No installed package was upgraded.

## Collected records and archives

The 2,202 installed binary-package records map to 1,180 source/version pairs:

| Material | Source/version pairs | Verification |
|---|---:|---|
| Matching versions in signed Raspbian/Raspberry Pi indexes | 1,065 | Index signature checked with the installed archive public key; source archives fully reread against SHA-256 |
| Historical exact-version .dsc records | 53 | Source/version and archive SHA-256 checked; developer signatures not independently verified |
| Exact-version Debian Snapshot candidates | 53 | Source/version and archive hashes checked; original Raspbian source input hashes still needed |
| Matching source not recovered | 9 | Listed below; no newer version substituted |

Across those materials and 20 Python source candidates, 3,545 distinct files
(5,416,308,124 bytes) were downloaded, retained in compressed form and fully
reread against SHA-256. All 1,171 collected .dsc source/version identities were
checked. The archives are held separately for internal source-delivery review;
this Git repository contains their identities and retrieval URLs, not the full
archive payloads. All original failed-transfer receipts were retained; one
observed disconnected transfer succeeded on a fresh-session retry.

See the [machine-readable inventory](../manifests/h102-rootfs-source-availability-1.2.0.json)
for exact filenames, versions, URLs, lengths and hashes. The existing
[installed package list](../manifests/h102-kuiper-1.2.0-installed-packages.tsv)
and [copyright index](../manifests/h102-kuiper-1.2.0-copyright-index.json) remain
available. A copyright index is an inventory, not a license grant.

## Exact versions still needed

| Source package | Installed source version |
|---|---|
| bluej-unbundled | `5.0.3` |
| chromium-browser | `126.0.6478.164-rpt1` |
| dpkg | `1.20.12+rpi1` |
| greenfoot-unbundled | `3.7.0` |
| python3.9 | `3.9.2-1+rpi1+deb11u2` |
| qtbase-opensource-src | `5.15.2+dfsg-9+rpi1+deb11u1` |
| scratch3 | `1.1.0` |
| systemd | `247.3-7+rpi1+deb11u6` |
| widevine | `4.10.2252.0+3` |

The original image provider's archives/build records or the relevant upstream
distribution channel are needed to close these entries. A clarification request
has been prepared but not sent. The package names alone do not determine their
individual source or redistribution requirements.

## Software outside dpkg

A separate bounded discovery found 23 Python distributions under /usr/local.
Matching PyPI source archives were obtained for 20 as candidates; this does not
prove those archives produced the installed wheels or cover bundled native
dependencies. Installed metadata identifies the adidt source commit
2f53fda5f49f1c2eb251f051aaca855001bba031; other manual build records remain needed.

Additional records include gtkdatabox 1.0.0, libusbgx 0.3.0, libm2k 0.9.0,
adi_colorimeter 1.0, local IIO tools and the Scopy v2.0.0-beta-rc2 armhf AppImage.
The inventory records observed versions and selected binary hashes. It does not
claim a complete inventory of every non-dpkg file, full embedded dependency
sources or exact source-to-binary reproduction for these components. H102
control-service, kernel-module and firmware materials are tracked separately.

## What this verifies

The checks establish archive integrity and stated source identities. They do
not establish a complete rootfs rebuild, all original build dependencies or
file-level distribution terms. The full-image source handoff remains open.
Keep the original component notices with every separate material delivery.

The [Raspbian repository](https://www.raspbian.org/RaspbianRepository/) and
[Debian Snapshot](https://snapshot.debian.org/) are upstream retrieval references.
See [source availability](SOURCE-AVAILABILITY.md) for the ADI SDK and other
component boundaries, and [boot rebuild](BOOT-REBUILD.md) for the separately
verified boot software.
