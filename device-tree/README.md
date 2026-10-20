# Reference H102 device tree

`h102-1.2.0-reference.dts` is decompiled with dtc from the original H102 DTB, SHA-256 `169feae5b8ba630c07628ae53d160778bdf3c71b8287838c99f34c2bfd518382`.

It is supplied for configuration inspection, not as the original maintained BSP source. It retains the original node/property values without adding board measurements. A DTS round-trip changes the binary hash; use the pinned original DTB for historical reconstruction. Confirm a modified tree against the actual RTL address map and qualify the resulting boot package before deployment.
