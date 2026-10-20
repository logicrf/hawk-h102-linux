# H102 IP-only device-control service

The control service exposes fixed operations on TCP **30432**. IIO IQ traffic uses port **30431**; USB IQ uses a separately installed host backend. The control API does not relay the IQ stream.

After matching services are installed, ordinary applications use the **device IP only**. They do not prompt for a Linux username, SSH password or sudo password. Administrator installation and legacy SSH examples are separate workflows.

## Service model

Requests select predefined operations and typed arguments. Clients cannot upload code, execute arbitrary commands or choose arbitrary device paths. The installation manifest pins helpers, SDK files and firmware. Native owners retain configuration/RX/GNSS locks, finite heartbeats and independent PID1 recovery. Disconnect closes worker input; neither the service nor client silently reconnects or restarts acquisition.

The service is designed for the device's trusted control network. This package does not claim network authentication or encrypted transport. Grant access only to the intended device-control clients.

## Administrator preparation

`build_bundle.py` requires explicit matching GUI/runtime, GNU Radio and already-released SDK-script directories. Those external fixed source inputs are not bundled by this image-integration repository. It verifies the complete SDK closure against the supplied GNU Radio lock and records actual file hashes and source provenance.

```bash
python3 control-api/build_bundle.py \
  --gui /inputs/matching-gui-runtime \
  --gr /inputs/matching-gr-logicrf \
  --sdk /inputs/matching-sdk-scripts \
  --output /work/new-control-bundle
sha256sum /work/new-control-bundle/assets.json
```

For an actual installation, transfer a reviewed complete package through the administrator's trusted maintenance channel. Verify the exact package, permissions, running firmware and idle state, then run the matching `install_service.py` as root. Never infer compatibility from the directory name or combine unrelated helper versions. The installer preserves old versions and verifies explicit previous hashes for upgrades.

English translation changes source hashes. The translated service source is a development/maintenance export, **not a drop-in replacement for a released service bundle**. Build and qualify a matching package before installation. Ordinary clients must continue using the version matched to their installed device service.

Persistent GRC add-on tools are included for maintenance review. They manage a paired bitstream/SDK/API set and require exact locks, backups, real idle state and a normal reboot. They are not needed just to connect to an already-prepared device.

## Protocol

Use UTF-8 JSON Lines, version 1, with a maximum frame length of 2 MiB including newline. Each ordinary connection carries one request and response; session connections retain the native control channel. Duplicate JSON keys, nonfinite numbers, oversized/nested input and unknown operations are rejected.

```json
{"version":1,"request_id":"0123456789abcdef0123456789abcdef","operation":"status","arguments":{}}
```

The Python client is under `h102_control`. `metadata` and `status` query the installed device; `configure` selects an approved preset. Session and evidence operations enforce installed entry points, source identity and issued session IDs. A timeout or disconnect does not prove a modifying operation succeeded: query actual state before deciding what to do next.

Protocol, transport and admission tests run offline. This source export adds no new live-board service installation or RF qualification.
