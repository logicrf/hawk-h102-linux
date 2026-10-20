# Component licenses and external inputs

This repository contains the H102 downstream integration toolkit. It does not grant a single license to the complete operating system or to third-party inputs.

| Component | Treatment |
|---|---|
| LogicRF-owned integration tools | Existing copyright notices are preserved. No new open-source license is granted by this private export. |
| Linux kernel and patches | Preserve the licenses of the affected upstream kernel files and each applicable module. Obtain the pinned ADI Linux checkout separately. |
| ADI Kuiper userspace base | Obtain the pinned original image separately and retain its notices. The current upstream Kuiper build-tool license is BSD-3-Clause; this is not a license for every package in its images. |
| ADRV9001 SDK 1.0.0 | User-supplied vendor input subject to its own agreement. SDK DLLs, C sources, firmware and stream binaries are not bundled here. |
| FTDI D3XX | Separately obtained and deployed under FTDI terms. No vendor library is included. |
| Generated radio profiles | Request catalogs and generator code are included. Generated profile/stream packages are supplied with a matching image or generated from licensed SDK inputs. |
| Complete RTL, GUI and host GNU Radio software | Separate products/repositories, not automatically licensed or included by this export. |

Upstream references: [Kuiper](https://github.com/analogdevicesinc/kuiper), [Kuiper license](https://github.com/analogdevicesinc/kuiper/blob/main/LICENSE), [ADI Linux](https://github.com/analogdevicesinc/linux).

Before any public source or image release, complete a per-component license review and provide all required corresponding source and notices. The earlier GPL decision for gr-logicrf does not relicense this repository.
