# Getting started with H102 Kuiper

LogicRF Hawk H102 Kuiper is the H102-specific Linux system based on ADI Kuiper. Use the H102 image supplied with the product; a generic ADI evaluation-board image does not contain the H102 boot files and hardware configuration.

## Prepare an SD card

1. Obtain the H102 1.2.0 `.img.xz` file and its checksum manifest from your delivery package.
2. Verify the SHA-256 checksum before writing. The compressed file is 2,759,144,392 bytes; the image expands to 11,823,742,976 bytes. Use an SD card larger than the expanded image.
3. Write the complete disk image using the supplied deployment tools or an image writer that supports the file format. Select the correct removable card; writing replaces its contents. Copying the file onto an existing SD partition is not sufficient.
4. Wait for writing and verification to finish, then safely eject the card.

The deployment tools and image are not included in this documentation branch. Refer to the instructions supplied with those tools for their exact commands and supported host systems.

## First boot

1. With the H102 powered off, insert the card and connect Ethernet to a DHCP network.
2. Power on and allow automatic first-boot setup to finish. Do not interrupt SD expansion or any resulting restart.
3. Find the assigned IP in your DHCP server/router, or use UART0 at 115200 baud, 8N1, no flow control and run `ip -4 address show dev eth0`.
4. For administrator setup, the initial account is `logicrf` with the initial password supplied in the device delivery instructions. Verify the device SSH host key before first administrator login. Ordinary GUI/GNU Radio connections use the device IP only.
5. Check that the board services are ready, then perform a short receive test with a configuration within your connection's data-rate limit.

First boot creates device-specific system/SSH identity and expands the root filesystem. Do not clone one running board's machine identity onto another board. The default radio profile is 40 MSPS / 20 MHz with independent RX/TX LOs.

## Connect an application

Use the standalone H102 IIO GUI or the GNU Radio `gr-logicrf` examples. Enter the actual device IP. IP-only applications require the matching device-control service to be installed first; the base 1.2.0 image does not imply that all later add-ons are present.

Start with dual RX at 8 MSPS / 4 MHz for Ethernet testing. Dual-channel 40 MSPS continuous IQ cannot fit within Gigabit Ethernet. USB 3.0 requires the matching host service and FT601 connection in addition to network control.

One application can use a device at a time. Stop reception/transmission and disconnect before opening another application. Before RF loopback tests, connect suitable attenuation and loads; never connect TX directly to RX.
