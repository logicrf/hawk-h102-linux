# Update an existing panel-compatible installation

The five-file panel1 update targets the exact EFA/cap3 H102 installation. Do not use it as a generic firmware flasher. A complete new installation should use the matching full SD image instead; see [SD installation](PANEL-SYSTEM.md).

An administrator stages the complete matched package in a root-owned directory and runs `python3 -B install_panel_addon.py --package-sha256 EXACT_PACKAGE_HASH`. The installer checks the original bitstream, SDK, API, service unit and idle state before creating durable backups. It writes the SDK/metadata first and the bitstream last. The API remains stopped until a normal SD reboot passes the paired startup checks.

For rollback, use the same package and hash with `--rollback`, then reboot normally. Unknown administrator changes are rejected rather than overwritten. Keep the transaction and original package until acceptance is complete.

Offline generation uses `control-api/prepare_panel_inputs.py` with the fixed original SDK, metadata, bitstream, firmware lock, API tree and service unit. Use the frozen EFA baseline inputs, not the latest mutable host-module lock. `control-api/package_panel_addon.py` packages the exact paired inputs and verifies an actual archive extraction. This does not rebuild or qualify a complete SD image.
