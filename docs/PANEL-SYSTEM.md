# Install the panel system image

Kuiper 1.2.1-rc1 is a complete H102 SD image with the panel bitstream, SDK and device-control service already integrated. It is a release candidate. Offline verification has passed; an SD card written from this exact image still needs physical cold-boot acceptance.

## Matching components

Use GUI 0.8.1 and gr-logicrf 1.2.3rc2 with this image. Normal applications connect using only the device IP address. No separate control-service installation or device Linux password is needed for ordinary operation. USB requires the documented one-time host setup.

S0 flashes once per second while the FPGA runs. S1 indicates host IQ activity and turns off when activity stops. Neither LED establishes RF level, GNSS lock or recording integrity.

## Prepare an SD card

Use the published image and its matching deployment-tool revision. The tool binds the compressed and raw SHA-256 values; it does not choose a target automatically. A full-card write erases the selected card. Back up any files you need before proceeding.

Run `python3 scripts/h102_sd_deploy.py list`, then `python3 scripts/h102_sd_deploy.py inspect --device /dev/SELECTED_CARD`. Check the reported model, capacity and identity, unmount its partitions, and use the current confirmation code with `sudo python3 scripts/h102_sd_deploy.py write --device /dev/SELECTED_CARD --image LogicRF-Hawk-H102-Kuiper-1.2.1-rc1-2024.1.img.xz --confirm CURRENT_CODE --report NEW_REPORT.json`. Replace the example device with the actual whole card. The report path must be new and its parent directory must exist. The tool writes, performs a complete direct readback and safely ejects the same device.

Insert the card into the powered-off H102 and power it on. First boot creates device-specific network and SSH identities and expands the root partition. Find its DHCP address and connect from the matching host application. Preserve the original card for rollback until the new installation has been accepted.

## Rebuild and verify

The image recipe starts from the exact 1.2.0 raw image, the reviewed panel SDK/API input set and the pinned base asset manifest. Run `scripts/prepare_h102_panel_image.py` with explicit input/output directories, then `scripts/build_h102_panel_image.py` with the base image, new stage and new output directory. Inputs remain unchanged. The recipe checks all packaged files, service links, filesystems, first-boot identity preparation and changes outside the declared file list. A rebuilt output is a new candidate requiring its own acceptance.

Vendor SDK/profile inputs and full root filesystem source materials remain subject to their separate availability and license records. This downstream integration toolkit does not claim complete corresponding source for the entire operating system. See [source availability](SOURCE-AVAILABILITY.md).
