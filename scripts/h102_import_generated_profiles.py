#!/usr/bin/env python3
"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_import_generated_profiles.py
@brief      Import approved offline H102 profile packages from pinned SDK generation receipts.
@details    Check complete hashes, success markers, stream version and four-channel settings
            before creating output. Merge partial runs only if complete and nonduplicate.
            Keep original blueprints/receipts; loading and data qualification remain separate.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    0.1.0
@date       2026-10-15
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import h102_profile_config as config

ROOT = Path(__file__).resolve().parents[1]
FILES = ('profile.json', 'stream.bin', 'request-blueprint.json',
         'stream-settings.json', 'generation-pass.json')
"""Native generated files that must have full hashes in the receipt."""


def collect(request_path, generation_directories):
    """Validate approved requests and native outputs before creating any output directory."""
    request = config.read_json(request_path)
    topology = request.get('lo_topology', 'independent')
    if topology not in ('independent', 'shared-lo2'):
        raise ValueError('REQUEST_LO_TOPOLOGY')
    pin = next(p for p in config.read_json(ROOT / 'manifests/h102-profile-generator-sdk-pins.json')
               ['sdk_packages'] if p['sdk_version'] == '1.0.0')
    if (request['schema'] != 1 or request['sdk_version'] != '1.0.0' or
            request['api_version'] != pin['api_version'] or request['device_clock_hz'] != 300000000 or
            request['interface'] != 'LVDS' or request['lanes'] != 2 or request['ddr'] is not True or
            request['iq_bits'] != 16 or request['duplex'] != 'FDD' or request['rx_ports'] != ['A', 'A']):
        raise ValueError('REQUEST_STACK_OR_INTERFACE_MISMATCH')
    wanted = {p['id']: p for p in request['profiles']}
    if not wanted or len(wanted) != len(request['profiles']):
        raise ValueError('REQUEST_IDS_EMPTY_OR_DUPLICATE')
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', k) for k in wanted):
        raise ValueError('INVALID_PROFILE_ID')
    found = {}
    for directory in generation_directories:
        receipt_bytes = (directory / 'generation-receipt.json').read_bytes()
        receipt = json.loads(receipt_bytes)
        if topology == 'shared-lo2':
            source_sha = {name: hashlib.sha256((ROOT / 'scripts/windows' / name).read_bytes()).hexdigest()
                          for name in ('H102ProfileGenerator.cs', 'h102-generate-profiles.ps1')}
            if (receipt.get('lo_topology') != topology or receipt.get('generator_source_sha256') != source_sha
                    or receipt.get('preset_catalog_sha256') != hashlib.sha256(request_path.read_bytes()).hexdigest()):
                raise ValueError('GENERATION_TOPOLOGY_OR_SOURCE_BINDING')
        if (receipt['schema'] != 1 or receipt['sdk_version'] != pin['sdk_version'] or
                receipt['api_version'] != pin['api_version'] or
                receipt['firmware_version'] != pin['firmware_version'] or
                receipt['stream_version'] != pin['stream_version'] or
                receipt['source_archive_sha256'] != pin['archive_sha256'] or
                receipt['sdk_pin_manifest_sha256'] != hashlib.sha256(
                    (ROOT / 'manifests/h102-profile-generator-sdk-pins.json').read_bytes()).hexdigest() or
                receipt['silicon_revision'] != 'C0' or receipt['device_clock_hz'] != 300000000 or
                receipt['interface'] != 'LVDS' or receipt['lanes'] != 2 or receipt['ddr'] is not True or
                receipt['iq_bits'] != 16 or receipt['duplex'] != 'FDD' or receipt['rx_ports'] != ['A', 'A'] or
                receipt['status'] not in ('generated_offline_not_board_qualified', 'partial_generation_failed')):
            raise ValueError('GENERATION_RECEIPT_STACK_MISMATCH')
        seen = set()
        for entry in receipt['profiles']:
            profile_id = entry['id']
            if profile_id in seen:
                raise ValueError('GENERATION_DUPLICATE_ID')
            seen.add(profile_id)
            if profile_id not in wanted:
                continue
            if profile_id in receipt.get('failed_ids', []) or profile_id in found:
                raise ValueError('FAILED_OR_AMBIGUOUS_GENERATION: ' + profile_id)
            blobs = {name: (directory / profile_id / name).read_bytes() for name in FILES}
            for name, blob in blobs.items():
                if hashlib.sha256(blob).hexdigest() != entry['sha256'][name]:
                    raise ValueError('GENERATION_DIGEST_MISMATCH: ' + profile_id + '/' + name)
            marker = json.loads(blobs['generation-pass.json'])
            if marker != {'success': True, 'warnings_rejected': True}:
                raise ValueError('GENERATION_NOT_PASSED')
            stream = blobs['stream.bin']
            if len(stream) != 32768 or '.'.join(str(n) for n in stream[8:11]) != pin['stream_version']:
                raise ValueError('STREAM_VERSION_OR_LENGTH')
            profile = json.loads(blobs['profile.json'])
            expected_los = {'rx1LoSelect': 2, 'rx2LoSelect': 2,
                            'tx1LoSelect': 2 if topology == 'shared-lo2' else 1,
                            'tx2LoSelect': 2 if topology == 'shared-lo2' else 1}
            if any(profile['clocks'].get(k) != v for k, v in expected_los.items()):
                raise ValueError('GENERATED_PROFILE_LO_MAPPING_MISMATCH')
            if topology == 'shared-lo2' and entry.get('lo_topology') != topology:
                raise ValueError('GENERATION_ENTRY_TOPOLOGY_MISMATCH')
            parameters = config.profile_parameters(profile)
            expected = wanted[profile_id]
            for row in (r for rows in parameters.values() for r in rows):
                for key in ('sample_rate_hz', 'rf_bandwidth_hz'):
                    if row[key] != expected[key] or entry[key] != expected[key]:
                        raise ValueError('REQUEST_PARAMETER_MISMATCH')
            # Receipts do not replace native-file checks: both RX TIA parameters must match the request.
            if (entry['rx_analog_corner_khz'] != expected['rx_analog_corner_khz'] or
                    any(channel['profile']['rxCorner3dB_kHz'] != expected['rx_analog_corner_khz']
                        for channel in profile['rx']['rxChannelCfg'][:2])):
                raise ValueError('REQUEST_ANALOG_CORNER_MISMATCH')
            blobs['generation-receipt.json'] = receipt_bytes
            manifest = dict(schema=1, id=profile_id, api_version=pin['api_version'],
                firmware_version=pin['firmware_version'], stream_version=pin['stream_version'] + '.0',
                parameters=parameters, sha256={name: hashlib.sha256(blobs[name]).hexdigest()
                    for name in ('profile.json', 'stream.bin')},
                generation_sha256={name: hashlib.sha256(blob).hexdigest()
                    for name, blob in blobs.items()}, online_generation=False,
                provenance=dict(generator='Windows ProfileArchitect SDK1.0.0; ProfileGen0.53.13',
                    sdk_zip_sha256=pin['archive_sha256'], silicon_revision='C0',
                    generation_receipt='generation-receipt.json',
                    request_catalog_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest()),
                clock=dict(device_clock_hz=300000000,
                    ssi_dclk_hz=expected['sample_rate_hz'] * 8,
                    native_clock_hz=expected['sample_rate_hz'] * 2,
                    pll_vco_hz=json.loads(blobs['profile.json'])['clocks']['clkPllVcoFreq_daHz'] * 10),
                qualification=dict(configuration_load='not_tested', iio='not_qualified',
                    usb='not_qualified', rf='not_qualified', gnss='not_qualified', board_qualified=False))
            manifest['rf_lo_topology'] = topology
            manifest['logical_profile_id'] = profile_id.removesuffix('-common') if topology == 'shared-lo2' else profile_id
            if receipt.get('generator_source_sha256'):
                manifest['provenance']['generator_source_sha256'] = receipt['generator_source_sha256']
            blobs['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
            found[profile_id] = blobs
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise ValueError('REQUESTED_GENERATION_MISSING: ' + ','.join(missing))
    return found


def main():
    """Import offline into a fresh directory and reuse runtime validation for approved packages."""
    parser = argparse.ArgumentParser(description='Import approved H102 profiles generated by the pinned SDK1')
    parser.add_argument('--request-catalog', type=Path, required=True)
    parser.add_argument('--generation-directory', type=Path, action='append', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    packages = collect(args.request_catalog, args.generation_directory)
    args.output_directory.mkdir(parents=True, exist_ok=False)
    config.configure_stack('sdk1-candidate')
    for profile_id, blobs in packages.items():
        directory = args.output_directory / profile_id
        directory.mkdir()
        for name, blob in blobs.items():
            (directory / name).write_bytes(blob)
        config.load_package(args.output_directory, profile_id)
    print(json.dumps(dict(status='imported_offline_not_board_qualified', count=len(packages),
        ids=list(packages)), ensure_ascii=False))


if __name__ == '__main__':
    main()

# End of file: h102_import_generated_profiles.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
