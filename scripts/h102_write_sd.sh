#!/bin/sh
# Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.
# H102 1.2.1: one-command launcher for the pinned SD deployment backend.
# The launcher never selects, unmounts, or formats a device automatically.
set -eu
umask 077

usage() {
    cat <<'EOF'
Usage: sudo sh scripts/h102_write_sd.sh --image IMAGE.img.xz --device /dev/SD --report NEW.json

Overwrites the explicitly selected SD disk after physical identity confirmation.
Checks the complete image, writes, performs full direct readback, and ejects.
Unmount SD partitions first. No separate decompression or formatting is needed.
EOF
}

image= device= report=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --image|--device|--report)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            case "$1" in
                --image) image=$2 ;;
                --device) device=$2 ;;
                --report) report=$2 ;;
            esac
            shift 2 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[ -n "$image" ] && [ -n "$device" ] && [ -n "$report" ] || { usage >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo 'Run this command with sudo.' >&2; exit 2; }
[ -f "$image" ] || { echo 'Image file not found.' >&2; exit 2; }
[ ! -e "$report" ] && [ ! -L "$report" ] || { echo 'Use a new report filename.' >&2; exit 2; }
[ -d "$(dirname -- "$report")" ] || { echo 'Create the report directory first.' >&2; exit 2; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
backend=$script_dir/h102_sd_deploy.py
inspection=$(mktemp)
trap 'rm -f -- "$inspection"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

echo 'LogicRF Hawk H102 | Kuiper 1.2.1 | SD deployment'
if ! python3 "$backend" inspect --device "$device" > "$inspection"; then
    cat "$inspection" >&2
    exit 2
fi
python3 -c '
import json, sys
d=json.load(open(sys.argv[1]))
i=d["identity"]
for label, key in (("Target", "device"), ("Bytes", "bytes"), ("Model", "model"),
                   ("Serial", "serial"), ("Disk sequence", "diskseq")):
    print(f"{label:14}: {i[key]}")
print("Blockers      :", d["blockers"])
print("Confirmation  :", d["confirm"])
' "$inspection"
token=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["confirm"])' "$inspection")
echo
echo 'ALL existing data on this target will be overwritten.'
printf 'Type the complete confirmation above to continue: '
IFS= read -r answer || { echo 'Cancelled.' >&2; exit 2; }
[ "$answer" = "$token" ] || { echo 'Confirmation mismatch. Nothing written.' >&2; exit 2; }
echo
echo 'Verifying the full compressed and raw image before writing...'
if python3 "$backend" write --image "$image" --device "$device" --confirm "$token" --report "$report"; then
    :
else
    deploy_status=$?
    if [ "$deploy_status" -eq 3 ]; then
        echo 'Image write and full direct readback passed. Safe ejection is still pending.' >&2
        echo 'Close users of this SD and safely eject it in the system before removing it.' >&2
        echo 'Do not repeat the image write to resolve an ejection-only failure.' >&2
    else
        echo "Deployment stopped. Check the phase and error in: $report" >&2
    fi
    exit "$deploy_status"
fi
echo
echo 'PASS: full image written, direct readback verified, SD safely ejected.'
echo 'Insert the SD into the powered-off H102, connect Ethernet, then power on.'
echo 'The stock image uses DHCP. A static-only network requires separate configuration.'
echo "Deployment receipt: $report"

# Contact: info@logicrf.com | Website: https://www.logicrf.com
