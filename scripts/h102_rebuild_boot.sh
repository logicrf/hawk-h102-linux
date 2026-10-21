#!/bin/bash
# Rebuild the released H102 boot software from the matching, separately supplied kit.
# The initial PL bitstream is a pinned binary input; this script does not build RTL.
set -euo pipefail

if [[ $# != 2 ]]; then
    echo "Usage: $0 BOOT_SOURCE_KIT NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi
kit=$(realpath "$1")
output=$(realpath -m "$2")
if [[ -e "$output" || "$output" == /dev/* ]]; then
    echo "Output must be a new regular workspace directory." >&2
    exit 2
fi
jobs=${H102_JOBS:-8}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || exit 2
xilinx=${H102_XILINX_ROOT:-/opt/xilinx}
cross="$xilinx/Vitis/2024.1/gnu/aarch32/lin/gcc-arm-linux-gnueabi"
bare="$xilinx/PetaLinux/components/xsct/gnu/aarch32/lin/gcc-arm-none-eabi/bin"
for tool in "$bare/arm-none-eabi-gcc" "$cross/bin/arm-linux-gnueabihf-gcc" \
    "$xilinx/Vivado/2024.1/bin/dtc" "$xilinx/Vitis/2024.1/bin/bootgen"; do
    [[ -x "$tool" ]] || { echo "Required tool unavailable: $tool" >&2; exit 2; }
done
(cd "$kit" && sha256sum -c SHA256SUMS)
mkdir -p "$output"/{fsbl,u-boot-source,u-boot-build,device-tree,pack,vendor}
cp -a "$kit/source/fsbl/." "$output/fsbl/"
mkdir -p "$output/fsbl/zynq_fsbl_bsp/ps7_cortexa9_0/lib"
tar -xzf "$kit/inputs/u-boot-source.tar.gz" -C "$output/u-boot-source"
# XilRSA is supplied as a binary library in the pinned upstream repository.
# Keep it explicit; it is not rebuilt from C by this recipe.
tar -xzf "$kit/inputs/embeddedsw-source.tar.gz" -C "$output/vendor" \
    lib/sw_services/xilrsa/src/librsa.a
echo "995ca7be364ea47da5d26be5199b0ce1e1ec2b325da6f4388babf0d121231007  $output/vendor/lib/sw_services/xilrsa/src/librsa.a" | sha256sum -c -
cp "$output/vendor/lib/sw_services/xilrsa/src/librsa.a" \
    "$output/fsbl/zynq_fsbl_bsp/ps7_cortexa9_0/libsrc/xilrsa_v1_8/src/"
cp "$kit/config/u-boot.config" "$output/u-boot-build/.config"
cp "$kit/config/platform-top.h" "$output/u-boot-source/include/configs/platform-top.h"

export TZ=UTC
export PATH="$bare:$cross/bin:$PATH"
export SOURCE_DATE_EPOCH=1716086412
# Finish BSP includes/libraries before compiling application objects.
make -C "$output/fsbl/zynq_fsbl_bsp" -j1 seq_libs
make -C "$output/fsbl/zynq_fsbl_bsp" -j"$jobs" par_libs
make -C "$output/fsbl/zynq_fsbl_bsp" -j1 archive
make -C "$output/fsbl" -j"$jobs"

# The SDK relocation wrapper adds '.real' to argv[0]. Preserve the original
# compiler name used in the released U-Boot version banner, with the same binary.
compiler="$cross/x86_64-petalinux-linux/usr/bin/arm-xilinx-linux-gnueabi"
loader=$(realpath "$compiler/../../../lib/ld-linux-x86-64.so.2")
libpath="$(realpath "$compiler/../../lib"):$(realpath "$compiler/../../../lib")"
cat > "$output/cross-gcc" <<EOF
#!/bin/bash
exec "$loader" --argv0 "$compiler/arm-xilinx-linux-gnueabi-gcc" --library-path "$libpath" "$compiler/arm-xilinx-linux-gnueabi-gcc.real" --sysroot="$cross/cortexa9t2hf-neon-xilinx-linux-gnueabi" "\$@"
EOF
chmod 755 "$output/cross-gcc"
export SOURCE_DATE_EPOCH=1715657508
make_args=(-C "$output/u-boot-source" "O=$output/u-boot-build"
    CROSS_COMPILE=arm-linux-gnueabihf- "CC=$output/cross-gcc")
make "${make_args[@]}" olddefconfig
host_args=()
if [[ -n ${H102_HOST_INCLUDE:-} && -n ${H102_HOST_GNUTLS:-} ]]; then
    host_args+=("HOSTCFLAGS_mkeficapsule.o=-O2 -I$H102_HOST_INCLUDE"
        "HOSTLDLIBS_mkeficapsule=-luuid $H102_HOST_GNUTLS")
fi
make "${make_args[@]}" "${host_args[@]}" -j"$jobs" u-boot
arm-linux-gnueabihf-objcopy --gap-fill=0xff -O binary \
    "$output/u-boot-build/u-boot" "$output/u-boot-build/u-boot.bin"

gcc -E -nostdinc -undef -D__DTS__ -x assembler-with-cpp \
    -I "$kit/source/dts" -I "$kit/source/dts/include" \
    "$kit/source/dts/system-top.dts" -o "$output/device-tree/system.dts.pp"
"$xilinx/Vivado/2024.1/bin/dtc" -I dts -O dtb -p 4096 -b 0 -@ \
    -i "$kit/source/dts" -o "$output/device-tree/system.dtb" \
    "$output/device-tree/system.dts.pp"
cat "$output/u-boot-build/u-boot.bin" "$output/device-tree/system.dtb" \
    > "$output/pack/u-boot-dtb.bin"
cp "$kit/config/binary-wrapper.ld" "$output/pack/"
cp "$kit/config/boot.bif" "$output/pack/"
cp "$kit/inputs/h102_logicrf.bit" "$output/pack/"
cp "$output/fsbl/executable.elf" "$output/pack/zynq_fsbl.elf"
(
    cd "$output/pack"
    arm-linux-gnueabihf-objcopy -I binary -O elf32-littlearm -B arm u-boot-dtb.bin u-boot-dtb.o
    arm-linux-gnueabihf-ld -T binary-wrapper.ld -e 0x04000000 -o u-boot-dtb.elf u-boot-dtb.o
    "$xilinx/Vitis/2024.1/bin/bootgen" -arch zynq -image boot.bif -o BOOT.BIN -w on
    echo '44b478bc7f38538f99d084551151639bef8ca5fbfc6378b26a564140d147a4b4  BOOT.BIN' | sha256sum -c -
)
echo "PASS: released BOOT.BIN reproduced at $output/pack/BOOT.BIN"
