# H102 IIO C++ and Python examples

Use these examples with matching H102 Kuiper 1.2.0 services and **libiio 0.x** (verified baseline 0.23). Plain queries require only an IIO URI. Connecting or querying does not create an IQ buffer.

## Build and query

On Ubuntu, install a C++17 compiler, CMake and libiio 0.x development/runtime packages. The basic Python example binds the C ABI with standard-library ctypes; do not install an unrelated Python package named iio.

```bash
cmake -S examples/iio/cpp -B /work/new-iio-example-build
cmake --build /work/new-iio-example-build -j8

python3 examples/iio/python/h102_api.py --uri ip:H102_IP xml
python3 examples/iio/python/h102_api.py --uri ip:H102_IP profiles
python3 examples/iio/python/h102_api.py --uri ip:H102_IP status
python3 examples/iio/python/h102_api.py --uri ip:H102_IP read adrv9002-phy frequency --channel altvoltage0 --output
/work/new-iio-example-build/h102_iio ip:H102_IP status
```

Replace H102_IP with the device address. Discover devices by stable names; do not hardcode iio:device indices. `status` double-checks configuration state/sequence rather than treating a crossed snapshot as current.

## Select a configuration

Stop other data clients first. An applied result must match the request ticket and independent readback; a rollback is not success.

```bash
python3 examples/iio/python/h102_api.py --uri ip:H102_IP select 8msps-4mhz
/work/new-iio-example-build/h102_iio ip:H102_IP select 8msps-4mhz-common
```

The actual selectable IDs come from `profiles`. Initialization can briefly affect RF, so use an appropriate connected/load environment. No arbitrary register-write example is provided.

## Finite IQ and advanced legacy wrappers

The native C++ and Python data cores require a real managed-session permit before buffer creation and I/O. `managed_iq.py` is the legacy administrator SSH wrapper for finite RX or RF-off TX submission. A successful single-channel receive returns 65,536 complex IQ16 samples, 262,144 bytes in little-endian interleaved signed I,Q. Dual selection captures channels serially, not simultaneously.

`managed_session.py` is a legacy adapter to the exact external GUI backend pinned by `runtime.lock.json`; that backend is not included in this repository. It supports advanced workflows only with the separately supplied matching runtime. These wrappers retain their original SSH credential interface and are **not the recommended ordinary IP-only client path**.

For ordinary password-free operation, use the matching gr-logicrf or H102 GUI release and installed [device-control service](../../control-api/README.md). Do not replace a real owner permit with an always-true callback outside the offline test fixtures. Preserve partial files on error; completion requires independent recovery before final file naming.

## Verification

`tests/test_iio_api_examples.py` builds the C++ core and runs Python/C++ against a local fault-injection libiio substitute when the matching headers are supplied. Tests check short I/O, errors, transaction conflict and buffer/context destruction. They do not qualify actual ADC data, continuous throughput or RF output.
