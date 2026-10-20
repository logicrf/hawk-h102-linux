"""Copyright (C) LogicRF Technologies (Chengdu) Co., Ltd. All Rights Reserved.

@file       h102_runtime_rates.py
@brief      Validate shared sample rates and digital bandwidth ranges in runtime templates.
@details    Match the RTL-approved 13 sample rates without device access or loading claims.
            Callers verify the approved catalog, hashes, actual channels and bitstream capabilities
            under configuration/RX/GNSS locks. Template encoding is not data authorization.
@author     LogicRF Technologies
@architect  LogicRF
@email      info@logicrf.com
@website    https://www.logicrf.com
@version    1.0.0
@date       2026-10-08
"""

import hashlib
import json

# Match runtime RTL capability 0x424 bit0: integer-Hz sample rates with denominator one.
SAMPLE_RATES_HZ = (192000, 768000, 1536000, 2000000, 4000000, 8000000,
                   10000000, 16000000, 20000000, 23040000, 30720000,
                   40000000, 61440000)


def validate_rate_bandwidth(expected_profile):
    """Return strict integer Fs/BW; reject bool, floats, unapproved rates and invalid bandwidth.

    This is an encoding boundary, not membership in an approved hardware configuration.
    """
    if (type(expected_profile) is not tuple or len(expected_profile) != 2 or
            any(type(value) is not int for value in expected_profile)):
        raise ValueError('INTEGER_RATE_BANDWIDTH_PAIR_REQUIRED')
    rate, bandwidth = expected_profile
    if rate not in SAMPLE_RATES_HZ or not 0 < bandwidth <= min(rate, 40000000):
        raise ValueError('UNSUPPORTED_RUNTIME_RATE_OR_BANDWIDTH')
    return rate, bandwidth


def verify_channels(applied, expected_profile):
    """Check physical channel order, denominator one and the caller's verified sample rate/bandwidth."""
    rate, bandwidth = validate_rate_bandwidth(expected_profile)
    channels = applied['channels']
    if (any(type(channel['channel']) is not int for channel in channels) or
            [channel['channel'] for channel in channels] != [1, 2]):
        raise ValueError('PHYSICAL_CHANNEL_ORDER')
    if any(type(channel[key]) is not int or channel[key] != wanted
           for channel in channels
           for key, wanted in (('sample_rate_num', rate), ('sample_rate_den', 1),
                               ('rf_bandwidth_hz', bandwidth))):
        raise ValueError('APPLIED_RUNTIME_PROFILE_MISMATCH')
    return rate, bandwidth


def _native_words(snapshot):
    """Check 24 raw uint32 words and reserved bits, returning two 384-bit channel records."""
    words = snapshot['words']
    if (type(words) is not list or len(words) != 24 or
            any(type(word) is not int or not 0 <= word < 2**32 for word in words)):
        raise RuntimeError('NATIVE_RAW_WORDS')
    rows = tuple(sum(words[12*ch+i] << (32*i) for i in range(12)) for ch in range(2))
    if any(raw >> 370 for raw in rows):
        raise RuntimeError('NATIVE_RAW_RESERVED')
    return rows


def _qualify_native_time(snapshot, mask, expected_profile, expected_epoch, *, cadence_baseline=None,
                         validated_checkpoint=False):
    """Check selected RX 2Fs cadence, samples/PPS and fresh epoch; default requires zero history.

    Use the verified active profile and the owner's new epoch, never arbitrary expected values.
    Check raw validity, faults, reserved bits and integer ranges before the 1000-ppm comparison;
    return decoded selected-channel tuples rather than trusting caller-provided decoded data.
    An optional raw baseline is captured by the same locked owner with stable configuration
    and time off. Check unchanged totals, nonreset ticks and a sub-wrap observation interval.
    Retain actual cumulative counts and baseline; never clear historical errors.
    Without a baseline preserve strict zero-history behavior; neither path qualifies USB or RF.
    Use monotonic_ns only for interval bounds, never synthesized UTC; invalid raw data raises.
    """
    rate, _ = validate_rate_bandwidth(expected_profile)
    if type(mask) is not int or mask not in (1,2,3):
        raise ValueError('NATIVE_PHYSICAL_MASK')
    if type(expected_epoch) is not int or not 0 < expected_epoch < 2**32:
        raise ValueError('NATIVE_NEW_EPOCH')
    rows = _native_words(snapshot)
    if (type(snapshot['time_epoch']) is not int or snapshot['time_epoch'] != expected_epoch or
            type(snapshot['source']) is not int or not 0 <= snapshot['source'] <= 31 or
            snapshot['source'] & 7 != 1):
        raise RuntimeError('NATIVE_RAW_EPOCH_OR_SOURCE')
    baseline_rows = None
    if cadence_baseline is not None:
        baseline_rows = _native_words(cadence_baseline)
        baseline_epoch = cadence_baseline['time_epoch']
        before_ns = cadence_baseline['monotonic_ns']; after_ns = snapshot['monotonic_ns']
        if (type(baseline_epoch) is not int or not 0 <= baseline_epoch <= expected_epoch or
                (baseline_epoch == expected_epoch) != validated_checkpoint or
                type(cadence_baseline['source']) is not int or
                not 0 <= cadence_baseline['source'] <= 31 or cadence_baseline['source'] & 7 not in ((1,) if validated_checkpoint else (0, 1)) or
                type(before_ns) is not int or type(after_ns) is not int or
                not 0 <= before_ns < after_ns or
                # Allow 200 ms for the two snapshots, each bounded by 100 ms, around ACK waiting.
                (after_ns-before_ns+200000000)*2*rate >= 2**32*1000000000):
            raise RuntimeError('NATIVE_CADENCE_BASELINE_WINDOW')
    result = []
    for index in range(2):
        if not mask & (1 << index):
            continue
        raw = rows[index]
        epoch = raw >> 208 & 0xffffffff
        period = raw >> 242 & 0xffffffff
        samples = raw >> 274 & 0xffffffff
        cadence = raw >> 306 & 0xffffffff
        pps_count = raw >> 338 & 0xffffffff
        if (raw >> 370 or not (raw >> 241 & 1) or epoch != expected_epoch or
                abs(period-2*rate) > 2*rate//1000 or abs(samples-rate) > rate//1000 or
                not pps_count):
            raise RuntimeError('NATIVE_TIME_OR_RUNTIME_RATE_NOT_QUALIFIED')
        baseline_count = 0
        if baseline_rows is not None:
            before = baseline_rows[index]
            baseline_count = before >> 306 & 0xffffffff
            if (cadence != baseline_count or (raw & ((1<<64)-1)) <= (before & ((1<<64)-1)) or
                    pps_count < (before >> 338 & 0xffffffff)):
                raise RuntimeError('NATIVE_CADENCE_INCREMENT_OR_RESET')
        elif cadence:
            raise RuntimeError('NATIVE_TIME_OR_RUNTIME_RATE_NOT_QUALIFIED')
        result.append(dict(channel=index+1, native_clock_hz=2*rate, period_ticks=period,
            samples_per_pps=samples, time_epoch=epoch, cadence_errors=cadence, pps_count=pps_count,
            sample_tick=raw & ((1<<64)-1), anchor_tick=raw >> 64 & ((1<<64)-1),
            utc_week=raw >> 128 & 65535, utc_tow_ms=raw >> 144 & 0xffffffff,
            pps_sequence=raw >> 176 & 0xffffffff, qerr_valid=bool(raw >> 240 & 1)))
        if baseline_rows is not None:
            result[-1].update(cadence_baseline=baseline_count, cadence_errors_since_baseline=0,
                cadence_observation_ns=after_ns-before_ns)
    return tuple(result)


def qualify_native_time(snapshot, mask, expected_profile, expected_epoch, *, cadence_baseline=None):
    """Keep short-window compatibility; a baseline precedes the fresh epoch and defaults to zero history.

    Check raw 24-word/PPS/Fs evidence and bounded counters without claiming data/RF qualification.
    Longer than the shortest 32-bit wrap interval requires verified NativeTimeWindow checkpoints.
    """
    return _qualify_native_time(snapshot, mask, expected_profile, expected_epoch,
                                cadence_baseline=cadence_baseline)


class NativeTimeWindow:
    """Track native time continuously with immutable evidence and permanently latched failure.

    Under three locks the owner commits RX templates, captures time-off baseline, then allocates epoch.
    This object neither accesses hardware nor holds locks; the caller owns provenance and recovery.
    Initial time acquisition may wait, but errors after qualification remain latched. Real snapshots
    must remain within the wrap interval. Host time bounds intervals, never constructs UTC.
    """
    def __init__(self, baseline, mask, expected_profile, expected_epoch):
        """Freeze time-off baseline and reject corrupt fields, invalid Fs/mask or nonfresh epochs."""
        self._profile = validate_rate_bandwidth(expected_profile)
        if type(mask) is not int or mask not in (1, 2, 3):
            raise ValueError('NATIVE_PHYSICAL_MASK')
        if type(expected_epoch) is not int or not 0 < expected_epoch < 2**32:
            raise ValueError('NATIVE_NEW_EPOCH')
        _native_words(baseline)
        if (type(baseline['time_epoch']) is not int or not 0 <= baseline['time_epoch'] < expected_epoch or
                type(baseline['monotonic_ns']) is not int or baseline['monotonic_ns'] < 0 or
                type(baseline['source']) is not int or not 0 <= baseline['source'] <= 31 or
                baseline['source'] & 7 not in (0, 1)):
            raise RuntimeError('NATIVE_WINDOW_INITIAL_BASELINE')
        self._first = self._freeze(baseline)
        self._mask, self._epoch = mask, expected_epoch
        self._last = None
        self._failed = False
        self._observations = 0

    @staticmethod
    def _freeze(snapshot):
        """Freeze a deep copy as JSON bytes so caller dictionary edits cannot change history."""
        return json.dumps(snapshot, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

    def observe(self, snapshot):
        """Decode and return historical/new counts, updating checkpoints only after all checks pass.

        Initial unlocked time raises the original acquisition error; corruption, changed counters,
        rollback, expiry or later loss of qualification permanently prevents subsequent success.
        """
        if self._failed:
            raise RuntimeError('NATIVE_WINDOW_FAILED_LATCHED')
        first = json.loads(self._first)
        checkpoint = json.loads(self._last) if self._last is not None else first
        try:
            rows = _native_words(snapshot); before = _native_words(checkpoint)
            if (type(snapshot['time_epoch']) is not int or snapshot['time_epoch'] != self._epoch or
                    type(snapshot['source']) is not int or not 0 <= snapshot['source'] <= 31 or
                    snapshot['source'] & 7 not in (0, 1)):
                raise RuntimeError('NATIVE_WINDOW_SOURCE_OR_EPOCH_CHANGED')
            for index in range(2):
                if not self._mask & (1 << index):
                    continue
                if (rows[index] >> 306 & 0xffffffff) != (before[index] >> 306 & 0xffffffff) or (
                        rows[index] & ((1<<64)-1)) <= (before[index] & ((1<<64)-1)) or (
                        rows[index] >> 338 & 0xffffffff) < (before[index] >> 338 & 0xffffffff):
                    raise RuntimeError('NATIVE_CADENCE_INCREMENT_OR_RESET')
            result = _qualify_native_time(snapshot, self._mask, self._profile, self._epoch,
                cadence_baseline=checkpoint, validated_checkpoint=self._last is not None)
            frozen = self._freeze(snapshot)
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            # Initial missing time anchor is acquisition; retries cannot erase other errors.
            acquiring = (self._last is None and isinstance(error, RuntimeError) and str(error) in (
                'NATIVE_RAW_EPOCH_OR_SOURCE', 'NATIVE_TIME_OR_RUNTIME_RATE_NOT_QUALIFIED'))
            if not acquiring:
                self._failed = True
            raise
        self._last = frozen
        self._observations += 1
        for row in result:
            row['cadence_interval_ns'] = row['cadence_observation_ns']
            row['cadence_observation_ns'] = snapshot['monotonic_ns']-first['monotonic_ns']
        return result

    def record(self):
        """Return fresh copies and source hashes without granting permission or hiding failed state."""
        return dict(schema=1, baseline=json.loads(self._first),
            baseline_sha256=hashlib.sha256(self._first).hexdigest(),
            last_qualified=json.loads(self._last) if self._last is not None else None,
            last_qualified_sha256=hashlib.sha256(self._last).hexdigest() if self._last is not None else None,
            observations=self._observations, failed=self._failed, time_epoch=self._epoch,
            mask=self._mask, expected_profile=list(self._profile))

# End of file: h102_runtime_rates.py
# Architect : LogicRF
# Contact   : info@logicrf.com
# Website   : https://www.logicrf.com
