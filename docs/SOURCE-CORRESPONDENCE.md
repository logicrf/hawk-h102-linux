# Matching the H102 1.2.0 source inputs

Later checkpoint: [boot software rebuild](BOOT-REBUILD.md) now verifies the generated BSP, reconstructed configuration and actual compilation against the released BOOT bytes, with explicit initial-PL/XilRSA binary inputs. See [rootfs source materials](ROOTFS-SOURCES.md) for the archive inventory. The initial audit below is preserved as a historical checkpoint; its NOT_RUN statements do not describe that later build.

The 21 October 2026 review matched the preserved kernel inputs to the actual release build and checked the BOOT composition. It did not change the image, compile new firmware or operate a device. Exact versions, complete hashes and scope are in the [source correspondence manifest](../manifests/h102-source-correspondence-1.2.0.json).

## Verified material

| Component | Result |
|---|---|
| ADI Linux base | Commit `c8daf49830b2d19b155756d151f4c881a001a67e` was fetched independently from the upstream Git repository and passed fsck. All 83,443 Git file entries and modes in the preserved base archive matched that commit. |
| Frozen release source | Replaying the six pinned kernel inputs and zero-fuzz patches reproduced all 83,492 source file/link entries from the real sharedlo1 build, including content hashes, modes and link targets. |
| Published preparation sequence | The English preparation tool verified the 141 SDK source files, two license documents and three initial profile pairs on a clean checkout. The subsequent calibration, register-bounds and shared-LO patches applied successfully. Source content matched the preserved build. |
| Kernel configuration and output | The actual configuration, Vitis 2024.1 AArch32 compiler identity and local-version arguments were recovered. The retained build's zImage matched the kernel extracted from the released FIT; the DTB and all 11 module hashes matched their pins. |
| External modules | Six original source/header/Makefile files for h102_axi_reg, h102_axi_trig and h102_profile_control matched the internal development source. Translated files keep their separate original/export hashes. |
| BOOT composition | Repacking the preserved FSBL, initial PL and U-Boot-with-control-DTB components using Bootgen 2024.1 produced exactly the released BOOT.BIN SHA-256. This was a packaging check, not a source rebuild of those components. |

The public preparation sequence keeps one additional SDK license PDF. It also uses 36 relative firmware links where the frozen build inputs used regular files with the same bytes. These are documented packaging differences; the two complete directory representations are not identical.

## Use the matching inputs

For development, follow [BUILD.md](BUILD.md): obtain the pinned upstream source and licensed SDK, verify the initial profiles, use an independent clean checkout and a new build directory, then apply the documented patches in order. The manifest records the full configuration/input hashes and expected kernel release. Do not substitute a later upstream branch or another SDK version.

Exact historical build inputs are retained separately from this integration repository. Some include vendor import changes and firmware, whose file-level distribution terms remain under review. They have not been uploaded as a complete source archive. A successful local replay does not itself grant redistribution rights or guarantee that a new compiler run produces identical binaries.

## BOOT and remaining source-delivery work

| Item | Availability and boundary |
|---|---|
| U-Boot | The retained 2024.1 recipe pins [Xilinx commit fbed1010](https://github.com/Xilinx/u-boot-xlnx/tree/fbed1010e50d75e7d25acc1c2d09e1c34cb7e882). Board configuration fragments, AR8035 enablement and build logs are retained. The full generated `.config` was not recovered after the historical cleanup task. A complete source rebuild/handoff remains open. |
| FSBL | The recipe pins [embeddedsw b173d246](https://github.com/Xilinx/embeddedsw/tree/b173d246826f662b9a98215d8f39e93d39d699b4), with Release optimization and FSBL_DEBUG_INFO. This recipe identity does not establish a reconstructed generated BSP or a byte-identical source build. |
| Root filesystem | Installed package/source-version and copyright hash indexes are available in the [new-card validation](CUSTOMER-SETUP-VALIDATION.md). Complete matching source archives and manually installed components are separate remaining work. |
| SDK and firmware | Preserve the applicable file notices and obtain the matching source-delivery status from LogicRF. Unresolved vendor file terms are not resolved by repository privacy or by these engineering checks. |

Upstream notices are available in the pinned [Linux COPYING](https://github.com/analogdevicesinc/linux/blob/c8daf49830b2d19b155756d151f4c881a001a67e/COPYING), [U-Boot license guide](https://github.com/Xilinx/u-boot-xlnx/blob/fbed1010e50d75e7d25acc1c2d09e1c34cb7e882/Licenses/README) and [embeddedsw file-level license index](https://github.com/Xilinx/embeddedsw/blob/b173d246826f662b9a98215d8f39e93d39d699b4/license.txt). Component and file terms remain separate. This page is an engineering source-availability record, not a complete system source distribution or a new license grant.
