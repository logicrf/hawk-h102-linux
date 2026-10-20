<#
LogicRF H102 Windows offline profile generator.
Verify all SDK DLL/resources inputs, generate the requested profiles and record parameters/hashes.
Do not connect to H102, approve generated presets automatically or load them onto hardware.
#>
param(
    [Parameter(Mandatory=$true)][ValidateSet('1.0.0','0.29.0')][string]$SdkVersion,
    [Parameter(Mandatory=$true)][string]$SdkRoot,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$PresetCatalog
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pinFile = Join-Path $repo 'manifests\h102-profile-generator-sdk-pins.json'
$pins = Get-Content -Raw $pinFile | ConvertFrom-Json
$pin = @($pins.sdk_packages | Where-Object sdk_version -eq $SdkVersion)[0]
$SdkRoot = (Resolve-Path $SdkRoot).Path
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path $OutputDirectory) { throw 'Output directory must be new; existing evidence cannot be overwritten.' }
foreach ($item in $pin.files.PSObject.Properties) {
    $file = Join-Path $SdkRoot $item.Name
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing SDK file: $($item.Name)" }
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Value) {
        throw "SDK file hash mismatch: $($item.Name)"
    }
}
foreach ($dir in @('prototype\DLLs','prototype\resources')) {
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $SdkRoot $dir) -File -Recurse) {
        $relative = $file.FullName.Substring($SdkRoot.Length + 1).Replace('\','/')
        if ($null -eq $pin.files.PSObject.Properties[$relative]) { throw "Unpinned SDK file: $relative" }
    }
}
$requests = @(
    [pscustomobject]@{id='40msps-20mhz';sample_rate_hz=40000000;rf_bandwidth_hz=20000000;rx_analog_corner_khz=10000},
    [pscustomobject]@{id='20msps-10mhz';sample_rate_hz=20000000;rf_bandwidth_hz=10000000;rx_analog_corner_khz=5000},
    [pscustomobject]@{id='8msps-4mhz';sample_rate_hz=8000000;rf_bandwidth_hz=4000000;rx_analog_corner_khz=3000}
)
$catalogSha = $null
$loTopology = 'independent'
if ($PresetCatalog) {
    $catalog = Get-Content -Raw -LiteralPath $PresetCatalog | ConvertFrom-Json
    if ($catalog.schema -ne 1 -or $catalog.sdk_version -ne $SdkVersion -or $catalog.api_version -ne $pin.api_version -or
        $catalog.device_clock_hz -ne 300000000 -or $catalog.interface -ne 'LVDS' -or $catalog.lanes -ne 2 -or
        !$catalog.ddr -or $catalog.iq_bits -ne 16 -or $catalog.duplex -ne 'FDD' -or ($catalog.rx_ports -join ',') -ne 'A,A') { throw 'Request SDK or fixed hardware scope mismatch.' }
    $requests = @($catalog.profiles)
    if ($catalog.PSObject.Properties['lo_topology']) { $loTopology = $catalog.lo_topology }
    $catalogSha = (Get-FileHash -LiteralPath $PresetCatalog -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($loTopology -cnotmatch '^(independent|shared-lo2)$') { throw 'Invalid LO topology.' }
$seen = @{}
if ($requests.Count -lt 1 -or $requests.Count -gt 128) { throw 'Invalid request count.' }
foreach ($request in $requests) {
    $rate = [uint32]$request.sample_rate_hz; $bandwidth = [uint32]$request.rf_bandwidth_hz
    if ($request.id -cnotmatch '^[a-z0-9][a-z0-9-]{0,63}$' -or $seen.ContainsKey($request.id) -or
        $rate -eq 0 -or $rate -gt 61440000 -or $bandwidth -lt 12000 -or $bandwidth -gt 40000000 -or
        $bandwidth -gt $rate -or [uint32]$request.rx_analog_corner_khz -eq 0) { throw 'Invalid request ID, sample rate or bandwidth.' }
    $seen[$request.id] = $true
}
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ('h102-generator-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $exe = Join-Path $temporary 'H102ProfileGenerator.exe'
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /platform:x64 "/out:$exe" (Join-Path $PSScriptRoot 'H102ProfileGenerator.cs')
    if ($LASTEXITCODE -ne 0) { throw 'C# generator compilation failed.' }
    $dlls = Join-Path $SdkRoot 'prototype\DLLs'
    $top = Join-Path $SdkRoot 'prototype\resources\AnalogDevices.Adrv9001.StreamGenAsm\asm\adrv9001\c0\top_level\top_level.txt'
    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
    $generatorExit = 0
    # SDK diagnostics accumulate across calls; use a new process and retain warnings per profile.
    foreach ($request in $requests) {
        $tsv = Join-Path $temporary ($request.id + '.tsv')
        $adcRate = 'HIGH'
        if ($request.PSObject.Properties['rx_adc_rate']) { $adcRate = $request.rx_adc_rate }
        if ($adcRate -cnotmatch '^(HIGH|MED|LOW)$') { throw 'Invalid ADC rate selection.' }
        $row = "{0}`t{1}`t{2}`t{3}`t{4}`t{5}" -f $request.id,$request.sample_rate_hz,$request.rf_bandwidth_hz,$request.rx_analog_corner_khz,$adcRate,$loTopology
        [System.IO.File]::WriteAllText($tsv,$row,[System.Text.UTF8Encoding]::new($false))
        $job = Join-Path $OutputDirectory ('_job-' + $request.id)
        & $exe $dlls $top $job $tsv
        if ($LASTEXITCODE -ne 0) { $generatorExit = 1 }
        $payload = Join-Path $job $request.id
        if (Test-Path -LiteralPath $payload) { Move-Item -LiteralPath $payload -Destination (Join-Path $OutputDirectory $request.id) }
        if (Test-Path -LiteralPath $job) { Remove-Item -LiteralPath $job }
    }
    $failed = @()
    $records = @()
    foreach ($request in $requests) {
        $rate = [uint32]$request.sample_rate_hz; $bandwidth = [uint32]$request.rf_bandwidth_hz
        $id = $request.id
        $dir = Join-Path $OutputDirectory $id
        if (!(Test-Path -LiteralPath (Join-Path $dir 'generation-pass.json') -PathType Leaf)) { $failed += $id; continue }
        $profile = Join-Path $dir 'profile.json'
        $stream = Join-Path $dir 'stream.bin'
        $p = Get-Content -LiteralPath $profile -Raw | ConvertFrom-Json
        $expectedTxLo = $(if ($loTopology -eq 'shared-lo2') {2} else {1})
        if ($p.clocks.rx1LoSelect -ne 2 -or $p.clocks.rx2LoSelect -ne 2 -or
            $p.clocks.tx1LoSelect -ne $expectedTxLo -or $p.clocks.tx2LoSelect -ne $expectedTxLo) { throw "LO mapping mismatch: $id" }
        if ($p.clocks.deviceClock_kHz -ne 300000 -or $p.sysConfig.duplexMode -ne 1 -or
            $p.clocks.rx1RfInputSel -ne 0 -or $p.clocks.rx2RfInputSel -ne 0 -or
            $p.rx.rxInitChannelMask -ne 195 -or $p.tx.txInitChannelMask -ne 12 -or
            $p.rx.rxChannelCfg.Count -ne 8 -or $p.tx.txProfile.Count -ne 2) { throw "Clock, mode or channel mismatch: $id" }
        foreach ($n in @(0,1)) {
            $rx = $p.rx.rxChannelCfg[$n].profile
            $tx = $p.tx.txProfile[$n]
            if ($rx.rxOutputRate_Hz -ne $rate -or $rx.rxInterfaceSampleRate_Hz -ne $rate -or
                $rx.primarySigBandwidth_Hz -ne $bandwidth -or $tx.txInputRate_Hz -ne $rate -or
                $tx.txInterfaceSampleRate_Hz -ne $rate -or $tx.primarySigBandwidth_Hz -ne $bandwidth) { throw "Sample rate or bandwidth mismatch: $id" }
            foreach ($ssi in @($rx.rxSsiConfig,$tx.txSsiConfig)) {
                if ($ssi.ssiType -ne 2 -or $ssi.numLaneSel -ne 1 -or
                    $ssi.ssiDataFormatSel -ne 4 -or !$ssi.ddrEn) { throw "SSI interface mismatch: $id" }
            }
        }
        $bytes = [System.IO.File]::ReadAllBytes($stream)
        $version = $bytes[8..10] -join '.'
        if ($bytes.Length -ne 32768 -or $version -ne $pin.stream_version) { throw "Stream size or version mismatch: $id" }
        $files = @{}
        foreach ($file in Get-ChildItem -LiteralPath $dir -File) {
            $files[$file.Name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $records += [ordered]@{id=$id;sample_rate_hz=$rate;rf_bandwidth_hz=$bandwidth;rx_analog_corner_khz=$p.rx.rxChannelCfg[0].profile.rxCorner3dB_kHz;lo_topology=$loTopology;sha256=$files}
    }
    $receipt = [ordered]@{
        schema=1;status=$(if ($failed.Count -eq 0) {'generated_offline_not_board_qualified'} else {'partial_generation_failed'});sdk_version=$SdkVersion;
        preset_catalog_sha256=$catalogSha;requested_count=$requests.Count;failed_ids=$failed;generator_exit=$generatorExit;
        api_version=$pin.api_version;firmware_version=$pin.firmware_version;stream_version=$pin.stream_version;
        source_archive_sha256=$pin.archive_sha256;sdk_pin_manifest_sha256=(Get-FileHash $pinFile -Algorithm SHA256).Hash.ToLowerInvariant();
        host=$env:COMPUTERNAME;silicon_revision='C0';device_clock_hz=300000000;interface='LVDS';lanes=2;ddr=$true;iq_bits=16;duplex='FDD';rx_ports=@('A','A');profiles=$records;
        lo_topology=$loTopology;generator_source_sha256=@{
            'H102ProfileGenerator.cs'=(Get-FileHash (Join-Path $PSScriptRoot 'H102ProfileGenerator.cs') -Algorithm SHA256).Hash.ToLowerInvariant();
            'h102-generate-profiles.ps1'=(Get-FileHash $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $json = $receipt | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText((Join-Path $OutputDirectory 'generation-receipt.json'),$json,[System.Text.UTF8Encoding]::new($false))
    if ($generatorExit -ne 0 -or $failed.Count -ne 0) { throw "Some profiles failed: $($records.Count)/$($requests.Count) succeeded; failure evidence and partial receipts retained." }
    Write-Output "$($records.Count) profiles generated and parameter/hash checked offline; H102 board qualification has not run."
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
