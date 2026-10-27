# Complete system image candidate

Kuiper 1.2.1-rc2 includes the H102 panel indicators, the matching device control API and the fixed SDK runtime. Use GUI 0.8.1 or the matching gr-logicrf 1.2.3rc3 package. The exact rc2 image has passed offline checks; SD deployment and hardware acceptance remain pending. The stable 1.2.0 release is unchanged.

The rc2 image corrects the private permissions of three API installation directories. The preceding rc1 booted Linux, but its API correctly rejected the directories created with 0755 permissions. A diagnostic repair to 0700 restored the API and passed short IIO RX and digital USB TX checks. That repair does not qualify the original rc1 image or the new rc2 image as a released system.

The new recipe records, sets and independently reads back root-owned 0700 permissions for the API root, bundle and package directories. File hashes, 618 installed files, five service links, filesystem integrity, first-boot identity preparation and changes outside the approved file list are checked separately.

The compressed image is 2,760,770,292 bytes, SHA-256 `31d554358ab80111c8b9244a93261e184c0766a13680fb860199a4154df5aea5`. Its decoded image is 11,823,742,976 bytes, SHA-256 `ce03f2d9cc496842548996bb18e14e5c2e4bfea10842dbc701bf7fb9833eec92`.

Use the pinned SD deployment tool with the exact rc2 manifest. The tool verifies the complete source, the selected disk identity, the complete direct readback and safe ejection. Keep the previous working card for rollback. Successful file verification does not establish cold-boot, RF, USB or profile-matrix qualification.
