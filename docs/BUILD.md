# Build inputs and development workflow

The repository is the H102 downstream integration toolkit, not a complete Linux distribution checkout. Start with the released image for ordinary deployment. Rebuilding a changed kernel or image is a development task requiring a matching set of external inputs and new validation.

## Required inputs

| Input | Identity / purpose |
|---|---|
| ADI Linux source | `c8daf49830b2d19b155756d151f4c881a001a67e` |
| ADRV9001 SDK ZIP | Version 1.0.0, SHA-256 in `manifests/h102-sdk1-linux-source-pins.json` |
| Generated initial profiles | Exact 40/20, 20/10 and 8/4 profile/stream pairs pinned in that manifest |
| Kernel configuration | `manifests/h102-sdk1-kernel.config` |
| Reference device tree | DTB SHA-256 `169feae5b8ba630c07628ae53d160778bdf3c71b8287838c99f34c2bfd518382`; obtain the matching original boot input |
| ARM cross compiler | Vitis 2024.1 AArch32 Linux GNU toolchain |
| Bootloader and RTL | Exact 1.2.0 BOOT/BIT/FIT/uEnv inputs in `manifests/h102-deployment-1.2.0.json` |
| Image reconstruction | Original fixed base images, asset/qualification receipts, original source Git objects, modules and generated profile packages required by each recipe |

Vendor SDKs, firmware, generated stream binaries, full kernel trees, original base images and compiled kernel archives are supplied separately. Existing recipes intentionally reject absent or changed inputs. They must not be made to pass by deleting hash, boot or qualification checks.

## Prepare kernel source

Use a clean independent ADI Linux checkout, a new output directory, and licensed inputs. These commands illustrate explicit paths; replace them with your own verified input locations:

```bash
python3 scripts/h102_prepare_sdk1_kernel.py \
  --sdk-zip /inputs/adrv9001-sdk-1pt0pt0.zip \
  --profiles-root /inputs/initial-sdk1-profiles --check-only

python3 scripts/h102_prepare_sdk1_kernel.py \
  --sdk-zip /inputs/adrv9001-sdk-1pt0pt0.zip \
  --profiles-root /inputs/initial-sdk1-profiles \
  --kernel-source /work/linux-source --kernel-build /work/linux-build
```

The preparation tool verifies the exact clean kernel commit, 141 SDK API sources, firmware, profiles and patch/configuration hashes before import. It preserves SDK license files. It does not compile or deploy.

For the release's additional driver changes, apply the calibration, bounded-register and shared-LO patches in order to that prepared source. Always run `git apply --check` before each application:

```bash
for patch in h102-sdk1-calibration-power.patch h102-adc-register-bounds.patch h102-fdd-shared-lo.patch; do
  git -C /work/linux-source apply --check "$PWD/patches/$patch"
  git -C /work/linux-source apply "$PWD/patches/$patch"
done

export H102_CROSS_COMPILE=/opt/xilinx/Vitis/2024.1/gnu/aarch32/lin/gcc-arm-linux-gnueabi/bin/arm-linux-gnueabihf-
make -C /work/linux-source O=/work/linux-build ARCH=arm \
  CROSS_COMPILE="$H102_CROSS_COMPILE" LOCALVERSION=-calfix1-regbounds1-sharedlo1 -j8 zImage modules
```

Verify the resulting kernel release rather than inferring it from the command. Build all three external modules against the same source/build tree: the legacy `h102_axi_reg` and `h102_axi_trig` sources under `references/h102-iio-legacy`, plus `kernel/h102-profile-control`. Use a new writable copy for out-of-tree module builds. Stage module installation separately; do not install ARM modules on the host.

The reference DTS is a decompiled configuration for inspection, not the original maintained BSP source. Recompiling a DTS or changing FIT timestamps can change binary hashes. A new kernel/FIT/module set requires consistent boot bindings and new candidate qualification.

## Image integration recipes

`scripts/prepare_h102_sdk1_assets.py` and `build_h102_sdk1_image.py` prepare the base SDK1 image. `build_h102_irq_hotfix_image.py`, `build_h102_driver_fix_image.py`, `prepare_h102_common_lo_assets.py` and `build_h102_common_lo_image.py` represent subsequent pinned integration steps. Their `--help` describes each stage's positional input paths.

These are historical, provenance-bound recipes. In particular, the original-source Git object and qualification records are **not** the English branch's HEAD, and translated runtime sources do not match original qualification hashes. For an exact historical reconstruction obtain those original pinned inputs through the product's source-delivery channel. Do not substitute this English checkout and label the output the already-qualified image. This source package alone cannot perform that full reconstruction.

For a new development build, review and freeze a new input set, generate new manifests and preserve both old/new source hashes. Qualify the resulting exact image and matching RTL before deployment. The English export does not issue a new image or change the released 1.2.0 hashes.

## Optional control-service runtime dependencies

The service also imports a matching installed SDK (`h102_runtime_usb_rx`) and fixed GUI/GNU Radio helpers (`runtime_archive`, `iio_runtime_archive`, `usb_runtime_candidate`, `usb_rx_reuse_candidate`). Those imports are preceded by package/installation identity checks and use explicit installed paths. They are external inputs, not unresolved local toolkit modules. The offline source checker lists them; it does not claim a complete service bundle or allow arbitrary helper replacement.

## Local source checks

```bash
python3 scripts/check_distribution.py
PYTHONPATH=scripts:control-api python3 -m pytest -q \
  tests/test_h102_deployment.py tests/test_iio_owner_lock.py \
  tests/test_network_performance.py tests/test_network_installer.py \
  tests/test_profile_iio_broker.py control-api/tests/test_protocol.py \
  control-api/tests/test_transport.py control-api/tests/test_native_contract.py
```

The tests use temporary regular files, real file locks and local protocol fixtures. They do not open SD devices or a board. Profile/SDK tests need separately supplied fixtures; C++ tests need libiio 0.x headers/runtime. See [verification scope](VALIDATION.md) for actual results of this package, including skipped inputs.

## Checked source correspondence

The [21 October source review](SOURCE-CORRESPONDENCE.md) exercised the preparation sequence and matched the frozen source to the actual release build. It documents the additional license PDF and firmware-link packaging differences. No new kernel was compiled by that review; source availability and vendor distribution terms remain separate.
