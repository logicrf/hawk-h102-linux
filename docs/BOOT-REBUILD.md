# Rebuild the H102 1.2.0 boot software

Use this procedure when preparing matching boot source materials or checking a
local rebuild. It reproduces the released BOOT.BIN while using the unchanged
initial PL bitstream. It does not build the runtime RTL or modify an SD card.

## Required inputs

Obtain `H102-BOOT-Source-Kit-1.2.0-r1.tar.xz` from LogicRF for the matching source
delivery review. The kit is currently retained internally, not published as a
GitHub download. Its size is 47747704 bytes and SHA-256 is:

```text
d6e59cbd5029a0dcfa21426b1017cdb57bd09adb489ab0c9964f9081ee5b2c38
```

The kit contains generated FSBL/BSP sources, the hardware export, original BSP
generation inputs, U-Boot sources and a complete reconstructed configuration,
control-device-tree sources, notices and input checksums. The full U-Boot
configuration was reconstructed from the pinned defconfig and H102 fragment;
the old generated file had been removed by the original rm_work step.

| Input | Fixed identity |
|---|---|
| embeddedsw | b173d246826f662b9a98215d8f39e93d39d699b4 |
| U-Boot | fbed1010e50d75e7d25acc1c2d09e1c34cb7e882 |
| ADI kernel DTS base and bindings | c8daf49830b2d19b155756d151f4c881a001a67e |
| Build tools | Vitis/Vivado/PetaLinux 2024.1; GCC 12.2.0; Binutils 2.39.0.20220819 |
| FSBL settings | UART0; Release -O2; FSBL_DEBUG_INFO |
| Expected BOOT.BIN | 44b478bc7f38538f99d084551151639bef8ca5fbfc6378b26a564140d147a4b4 |

## Build in a new directory

The Linux host needs GCC, make, flex, bison, OpenSSL/GnuTLS development headers
and libraries, and libuuid. The script uses the Xilinx installation under
`/opt/xilinx` and defaults to eight jobs. Extract the verified kit, then run:

```sh
bash scripts/h102_rebuild_boot.sh /path/to/H102-BOOT-Source-Kit-1.2.0-r1 \
  /path/to/new-h102-boot-build > h102-boot-build.log 2>&1
```

The output directory must not already exist. Set `H102_XILINX_ROOT` to use
another installation prefix or `H102_JOBS` to change concurrency. The script
checks the kit inputs, builds BSP libraries before application objects, compiles
U-Boot and the device tree, wraps the binary into a loadable ELF, and runs
Bootgen. Success ends with the complete released BOOT SHA check.

For an isolated GnuTLS development tree, optional `H102_HOST_INCLUDE` and
`H102_HOST_GNUTLS` identify the host include directory and actual library file.
The script does not install system packages or connect to hardware.

## BSP regeneration

The kit includes `generation/app.tcl`, `generation/fsbl.yaml`,
`inputs/system.xsa` and `inputs/embeddedsw-source.tar.gz`. To regenerate in
a separate workspace, extract that pinned archive and invoke XSCT 2024.1 with:

```sh
xsct -sdx -nodisp generation/app.tcl \
  -ws /path/to/new-xsct-workspace -pname fsbl-firmware \
  -rp /path/to/extracted-embeddedsw \
  -processor_ip ps7_cortexa9 -processor ps7_cortexa9_0 \
  -hdf inputs/system.xsa -arch 32 -app "Zynq FSBL" \
  -yamlconf generation/fsbl.yaml
```

This invocation was used for the source review. The direct build command uses
the kit's generated sources, so it does not need to regenerate them.

## Reproducibility and component limits

A clean-directory run rebuilt FSBL/BSP, U-Boot and the control DTB. Allocated ELF
sections and entry addresses matched the release; the U-Boot BIN and DTB were
byte-identical. Using the unchanged initial PL produced a byte-identical
BOOT.BIN. Whole ELF files differ in nonloaded debug/path metadata.

The recipe preserves original commit-time SOURCE_DATE_EPOCH values and the
original logical GCC executable name in the U-Boot version banner. It also
uses the ADI kernel Zynq base DTS before the different generated Xilinx copy.
These are recorded build inputs, not post-build binary edits.

Upstream XilRSA is an explicit binary dependency: `librsa.a`, 12,530 bytes, SHA-256
`995ca7be364ea47da5d26be5199b0ce1e1ec2b325da6f4388babf0d121231007`.
Its C implementation was not found in the reviewed upstream archive; the
script extracts the original library from that pinned archive. The initial PL
also remains a prebuilt input. This is not a claim that every dependency was
rebuilt from source, a complete system source delivery, or a new component
license grant. See [the source manifest](../manifests/h102-boot-source-rebuild-1.2.0.json),
[source availability](SOURCE-AVAILABILITY.md) and [rootfs sources](ROOTFS-SOURCES.md).
