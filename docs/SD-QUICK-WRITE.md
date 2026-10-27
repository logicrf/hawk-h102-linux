# Write an H102 SD card with one command

Use these Linux tools with the Kuiper 1.2.1 image. Python 3.10+, `lsblk`, `udisksctl` and `sudo` are required. The image is downloaded separately. The tool streams `.img.xz` directly; no separate decompression, formatting or resizing is needed.

Insert the SD into the computer and identify its **whole-disk** device path. A 32 GB or 64 GB card is recommended; the target must hold at least 11,823,742,976 bytes. Back up previous card data. Unmount any mounted SD partitions before continuing; do not select a system disk, backup disk or partition path.

From the tool-package root, run:

```sh
sudo sh scripts/h102_write_sd.sh \
  --image /path/to/LogicRF-Hawk-H102-Kuiper-1.2.1-2024.1.img.xz \
  --device /dev/disk/by-id/your-sd-reader \
  --report "$PWD/H102-SD-001.json"
```

Replace both paths with the actual image and SD disk. Use a new report filename. Here, `sudo` grants permission to write the computer's SD device; it is separate from an H102 login.

The launcher displays the target capacity, model, serial number and confirmation token. Check the physical card and type the complete token shown on screen. The token is bound to the current device and disk sequence: removing or replacing the card requires a new inspection. Never copy a token from another card or a screenshot. Confirmation permits the target's previous layout and data to be overwritten.

The tool then verifies the full compressed and raw image hashes, checks target use, writes through an exclusive device descriptor, flushes the write, reads back the complete image length with `O_DIRECT`, and safely ejects the original device. It never guesses a target, automatically unmounts a card, terminates another owner, or retries image writes after failure.

| Result | Action |
| --- | --- |
| Exit 0, `PASS_WRITE_DIRECT_READBACK_EJECT` | Write, direct readback and safe ejection passed; remove the card |
| Exit 3, `WRITE_VERIFIED_NOT_EJECTED` | Write/readback passed; close users of this SD and safely eject it through the operating system before removing it |
| Other failure | Read the reported phase and error; retain the report and resolve the cause before another operation |

A transient block-device user can delay ejection by up to five seconds. Identity and use are checked again each time. Persistent use, a mount, replacement card or inspection error still prevents ejection. Do not rewrite an already verified image to resolve an ejection-only refusal. Reports created by `sudo` can be read with `sudo cat`.

Insert the card into the powered-off H102, connect Ethernet and then power on. First boot creates independent device identities, expands the root filesystem and starts the matching services. **The stock image uses DHCP.** Obtain the actual address from the router's lease list or UART0. A static-only network needs the [UART static IPv4 setup](https://docs.logicrf.com/en/hawk-h102/system#static-ipv4); this writer does not preconfigure network settings.

Ordinary GUI and GNU Radio use requires only the device IP. Linux credentials are for maintenance and the optional administrator check. See the [illustrated first-use guide](https://docs.logicrf.com/en/hawk-h102/new-device-deployment) for connection, profile selection and reception.
