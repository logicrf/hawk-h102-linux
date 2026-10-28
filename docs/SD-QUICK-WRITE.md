# Write an H102 SD card with one command

Use deployment tools **0.3.0** with the Kuiper 1.2.1 image. The default network mode tries DHCP first, then uses **10.168.1.199/24** if no lease is obtained. The image is downloaded separately. No separate decompression, formatting or resizing is needed.

The Linux computer needs Python 3.10+, `lsblk`, `udisksctl`, `sudo`, `debugfs`, `e2fsck`, and kernel loop-device support. `debugfs` and `e2fsck` are supplied by the distribution's e2fsprogs package. The tools check requirements before writing and do not install dependencies automatically.

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

The tool verifies the complete compressed and raw image hashes, checks target use, writes and flushes the image, reads back the complete image length with `O_DIRECT`, applies and checks the selected network settings, and safely ejects the original device. It never guesses a target, automatically unmounts a card, terminates another user of the device, or retries image writes after failure.

| Result | Action |
| --- | --- |
| Exit 0, `PASS_WRITE_DIRECT_READBACK_EJECT` | Write, direct readback and safe ejection passed; remove the card |
| Exit 3, `WRITE_VERIFIED_NOT_EJECTED` | Write/readback passed; close users of this SD and safely eject it through the operating system before removing it |
| Other failure | Read the reported phase and error; retain the report and resolve the cause before another operation |

For the default `auto` mode, the report also contains `network_personalization.status=PASS_NETWORK_PROFILES_READBACK_EXT4`. This verifies the five installed network files, their permissions and the root filesystem. The base-image readback happens before network customization, so the final card is expected to differ from the unmodified RAW image. Keep the complete report.

A transient block-device user can delay ejection by up to five seconds. Identity and use are checked again each time. Persistent use, a mount, replacement card or inspection error still prevents ejection. Do not rewrite an already verified image to resolve an ejection-only refusal. Reports created by `sudo` can be read with `sudo cat`.

## Connect after first boot

Insert the card into the powered-off H102, connect Ethernet and then power on. First boot creates independent device identities, expands the root filesystem and starts the matching services.

- **With DHCP:** use the address assigned by the server. Find it in the router's lease list or on UART0; it will not necessarily be 10.168.1.199.
- **Without a usable DHCP lease:** the DHCP transaction times out after approximately 15 seconds, then H102 activates 10.168.1.199/24. Configure the computer's Ethernet interface with an unused address in that subnet, such as 10.168.1.200/24. A local connection needs no gateway or DNS.

The 15-second timeout covers the DHCP transaction, not the complete board startup. Connect Ethernet before powering on. Once static fallback is active, a returning DHCP server does not change the address during reception; stop the session and restart the board or have an administrator switch the network when needed.

Power on one unconfigured H102 at a time on a network without DHCP. Devices sharing a subnet need different static fallback addresses. To provision another fallback address, add `--address 10.168.1.198/24` to the write command.

**The original 1.2.1 image file remains unchanged.** Automatic fallback is installed by these deployment tools. Writing the same image with another program retains its original DHCP-only settings.

## Choose a different network mode

| Write option | Startup behavior |
| --- | --- |
| Omit network options, or add `--network auto` | DHCP first; static fallback defaults to 10.168.1.199/24 |
| `--network dhcp` | DHCP only |
| `--network static --address 10.168.1.199/24` | Use the specified static address immediately |

For a routed static network, optional `--gateway` and `--dns` values must describe the actual network. See the [detailed deployment guide](DEPLOYMENT.md). Existing cards can also use the [administrator UART IPv4 procedure](https://docs.logicrf.com/en/hawk-h102/system#static-ipv4).

Ordinary GUI and GNU Radio use requires only the device IP. Linux credentials are for maintenance and the optional administrator check. See the [illustrated first-use guide](https://docs.logicrf.com/en/hawk-h102/new-device-deployment) for connection, profile selection and reception.
