# Source records for manually installed components

This review covers selected components outside the dpkg source inventory in Kuiper
1.2.0. The original system was queried without rebuilding, installing software or
changing device operation. The [source manifest](../manifests/h102-manual-source-provenance-1.2.0.json)
records fixed commits, archive hashes and verification limits.

## Retained source trees

Thirteen repositories under the original system's `/usr/local/src` supplied 995
tracked files and 146 small build records. Each HEAD file list, Git blob identity
and mode was checked against its official GitHub commit tree. The retained file
contents were checked separately: only `fru_tools/.version` differs, containing
`8` instead of the upstream `7`. All file modes match. The archive preserves the
actual retained file. Stale Git index stat records had marked many unchanged
files as modified; these indicators were not used as evidence of content changes.

| Component | Fixed commit |
|---|---|
| colorimeter | `db018d4c03233b6d27bfd2edc6632715df2aeb9e` |
| diagnostic_report | `fc0ba060a9fb43d0aea07a1258ee40b0ef31b6c7` |
| fru_tools | `4a18979382d59dd956bc11a6606d460e3f8937ca` |
| gt | `a2aa973640dcfde4de1ebc4bc4906195ba5826f9` |
| iio-fm-radio | `e67be7eb2ca539008fd4dde9469dbf402d7b40cb` |
| iio-oscilloscope | `89b3848e85a7696ec468ca992c575ea2eb02dd56` |
| jesd-eye-scan-gtk | `f3babfb9f02933936ff5ca56aa1add01fec9d1a4` |
| libad9166-iio | `2916da36a01aeb0f1022d80a5cc48c782da17563` |
| libad9361-iio | `d692a52a869ac2665e9e49907c7e0db41c4d13f6` |
| libiio | `5e1e9cb567ffd6d6d810fdd7c44fe79e9613f56a` |
| libusbgx | `dbedf16f80c5b4e1807ea4f80cc89d1f15d36f0a` |
| linux_image_ADI-scripts | `c643dd0fbc4277bf88111940fa6f4f948b7f83e6` |
| wiki-scripts | `ded20fd1fcbde0abd926ba955198aa608a54b805` |

`Kuiper-retained-project-sources-r1.tar.gz` is 41,960,583 bytes, with SHA-256
`148a80e72eddc6e3de4d30ce2bd656aa1f59771f6991e91e8326bb35fe864353`.
Every source member and build record was read back and hashed locally. Original
upstream notices remain in the trees. The archive excludes `.git`, large build
binaries and unrelated filesystem content.

## Checks against installed files

| Component | Verified correspondence | Limit |
|---|---|---|
| adidt 0.0.1 | Archived the installed direct_url commit `2f53fda5f49f1c2eb251f051aaca855001bba031`; all 31 installed .py files listed in RECORD match | Includes test files; does not reconstruct bytecode, entrypoints or dependencies |
| adi_colorimeter 1.0 | All five installed .py files match retained source, including a separately preserved generated config.py | capture.so and dependencies were not rebuilt |
| libm2k 0.9.0 | Installed version header identifies `ce0cf95`, matching official v0.9.0 and the historical recipe; source archived | Does not establish reproducible native binaries |
| iio_fm_radio, libusbgx, jesd_eye_scan, jesd_status, iio_jesd204_fsm_sync | Five installed files have the same full SHA-256 as retained build outputs | No fresh compilation or dependency rebuild |
| osc | Initial full hashes differ only through .dynstr/.dynamic. Replaying the recorded RPATH_CHANGE on a local build-file copy produces the exact installed file hash | Reproduces the install transformation, not compilation; initial failed comparisons remain recorded |

The historical generator tag `2023_r2_p1`, commit
`3126a323b1c03042ab91f086d2780f27030dc5f5`, selects libm2k v0.9.0 and deletes its
source directory after installation. It also deletes gr-iio and gr-m2k source
checkouts. The release label and date match the upstream image, but the original
image-generation job receipt was not recovered; the exact generator checkout
therefore remains unconfirmed.

## Additional candidates and remaining gaps

Official BlueJ 5.0.3 and Greenfoot 3.7.0 source ZIPs were retrieved and passed CRC
checks. Their Raspberry Pi unbundled packaging inputs remain missing, so the
count of nine unresolved exact packaged source versions is unchanged. The
historical recipe's gtkdatabox 1.0.0 URL supplied a verified source archive; its
original download hash and binary build provenance remain unconfirmed. Eight
supplementary inputs total 113,549,902 bytes, all read back with SHA-256. The
previous 3,545 rootfs archive objects remain unchanged.

The Scopy armhf AppImage build and bundled third-party inputs, deleted gr-iio and
gr-m2k checkout identities, and other Python/native build dependencies remain
open. SDK file-level terms and delivery terms for the XilRSA prebuilt dependency
are separate unresolved items. Source identity, archive integrity, binary
reconstruction and component terms have distinct verification scopes.

The system's retained upstream LICENSE.html contains a written source offer and the date
text `18Sep2028`; its product-name template field is empty. The original file and
hash have been retained. The offer is retained as upstream documentation. An ADI inquiry or response is
not a prerequisite for development or material assembly. No request has been
sent or fulfilled. This upstream text does not
establish a LogicRF offer or cover downstream additions automatically.

Check [source availability and component terms](SOURCE-AVAILABILITY.md) and contact
LogicRF for matching materials. Complete system corresponding-source delivery
remains open.
