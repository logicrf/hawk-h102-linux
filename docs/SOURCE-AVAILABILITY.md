# Source availability and component terms

Use the component source package that matches your binary version. Source access
and redistribution terms remain component-specific. Private repository access is
not a replacement for any source or notice obligations owed to a recipient.

| Component | Available material | Current boundary |
|---|---|---|
| gr-logicrf 1.2.2rc2 | [GPL source release](https://github.com/logicrf/gr-logicrf/releases/tag/v1.2.2-rc2), build scripts and bundled minimal control runtime | Vendor USB libraries and board firmware are separate |
| IIO GUI 0.8.0 source r2 | [Private source release](https://github.com/logicrf/hawk-h102-iio-gui/releases/tag/v0.8.0-source-en-r2) and dependency requirements | Existing LogicRF delivery terms; dependencies keep their own licenses |
| H102 Linux integration | This repository's patches, configuration, scripts and pinned inputs | Not a complete corresponding-source package for the SD image |
| Linux kernel | ADI upstream commit `c8daf49830b2d19b155756d151f4c881a001a67e` plus H102 changes described in [BUILD.md](BUILD.md) | Exact full source delivery, SDK import terms and final build input availability remain under review |
| Kuiper base and installed packages | Upstream source and per-package notices | Installed package/source-version and copyright hash indexes are available in the [new-card validation](CUSTOMER-SETUP-VALIDATION.md); matching source archives and a complete system inventory remain open |
| SDK, firmware, streams and generated profiles | Product-specific vendor inputs and matched binary payloads | Do not infer a general SDK source-redistribution grant from image or toolkit access |
| BOOT, RTL and USB host components | Separate product inputs | Their source/IP and vendor terms are not granted by the GNU Radio module's GPL license |

The SDK 1.0.0 input includes package-level and separate SLA notices. API file
headers refer to a license file that was not found under that name in the reviewed
ZIP. The applicable file-level terms and the source delivery path for imported
kernel API files need clarification; this repository does not claim that issue is
resolved. Ask LogicRF for the matching source-delivery status before redistributing
a system image or vendor components.

[ADI kernel COPYING](https://github.com/analogdevicesinc/linux/blob/c8daf49830b2d19b155756d151f4c881a001a67e/COPYING),
[Linux licensing rules](https://www.kernel.org/doc/html/latest/process/license-rules.html),
[Kuiper LICENSE](https://github.com/analogdevicesinc/kuiper/blob/main/LICENSE),
and [ADI software terms](https://www.analog.com/en/support/software-license-agreement.html)
are upstream references. The build-tool license alone does not cover all image
packages. Preserve the exact shipped version's notices and any separately agreed
terms. This page records availability; it does not issue a new license or a
complete system compliance certification.
