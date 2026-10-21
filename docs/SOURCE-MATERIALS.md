# Export Kuiper 1.2.0 source materials offline

Export the collected archives with original filenames and source/version
directories for inspection and build preparation. Source provenance and candidate
labels are preserved. See the [package inventory](../manifests/h102-rootfs-source-availability-1.2.0.json),
[manual component records](MANUAL-SOURCES.md) and
[copyright archive manifest](../manifests/h102-copyright-materials-1.2.0.json)
for their separate scopes.

## Prepare the inputs

Use Python 3.10 or newer, this repository and the matching source-review cache.
The cache is separate from the SD image and is not included in this Git checkout.
Keep the following directory names when obtaining matching materials:

```text
source-review/
  1.2.0-rootfs-20261021/objects/<SHA256>
  1.2.0-manual-20261021/<original-filename>
  1.2.0-notices-20261021/H102-Kuiper-1.2.0-installed-copyrights.tar.gz
```

The rootfs collection contains 3,545 distinct files totaling 5,416,308,124 bytes;
eight manual supplements total 113,549,902 bytes. The copyright archive contains
the exact content of 2,191 indexed installed files, totaling 173,998,822 bytes
before compression. The archive is 23,776,478 bytes, with SHA-256
`75caf976e894453437c468cfb458902e90f16ccb6ae6f33ef9814836463e2b8a`.
Indexed symlink contents are archived as regular files under their package-doc
names. This makes those notices retrievable; it does not establish complete
bundled-dependency coverage or complete system license review.

## Verify and export

Verify cached inputs without writing an export:

```sh
python3 scripts/h102_export_source_materials.py /path/to/source-review
```

Copy into a new output directory whose parent already exists:

```sh
python3 scripts/h102_export_source_materials.py /path/to/source-review \
  --output /path/to/new-h102-source-materials
cd /path/to/new-h102-source-materials
sha256sum -c SHA256SUMS
```

For internal storage, add `--hardlink` to share read-only cache files on the same
filesystem. Do not edit a hardlink export: copy a material into a separate working
directory first. The tool never changes input permissions, removes old outputs
or overwrites an existing export. Missing/corrupt inputs, symlinks, unsafe paths,
conflicting destinations and filesystem errors produce a nonzero exit. An
interrupted output is retained for diagnosis; success is printed only when the
whole operation finishes.

## Export layout

| Path | Material and interpretation |
|---|---|
| rootfs/source/version/ | Signed-index or historical exact-version materials; .dsc and referenced inputs are adjacent under original filenames |
| candidates/debian/source/version/ | 53 exact Debian-version candidates; original Raspbian input provenance remains open |
| candidates/python/name/version/ | 20 PyPI source candidates; original wheel inputs are not established |
| manual/ | Supplements including the 13 retained source trees, fixed adidt input and libm2k material; consult individual provenance records |
| notices/ | Archive matching the 2,191-path installed copyright index |
| manifests/ | Four exact input manifests used for the export |
| SOURCE-MATERIALS.json | Output paths, hashes, provenance and remaining gaps; complete_system_corresponding_source remains false |
| SHA256SUMS | Independent checksum entry point for materials and metadata |

On a Linux host, a collected source package can be unpacked with standard Debian
tools. For example:

```sh
dpkg-source --no-check -x rootfs/a52dec/0.7.4-20/a52dec_0.7.4-20.dsc /path/to/new-a52dec-source
```

`--no-check` skips DSC signature verification; first verify the full SHA256SUMS
file. Historical developer signatures remain independently unverified where
recorded. Successful extraction does not establish reproducible installed
binaries or change the H102. Keep component copyright, license and patch notices.

## Availability limits

The tool exports all available indexed materials without network or device
access and never executes archives. Nine exact packaged source records and
further dependency inputs remain unresolved. Debian candidates retain their
original Raspbian provenance limitation. Remaining materials are assembled from
public project sources, existing recipes and component licenses; an ADI response
or separate release approval is not a prerequisite for this workflow.

The boot kit, complete kernel inputs, SDK and RTL are separate materials. Follow
[boot rebuild](BOOT-REBUILD.md), [kernel correspondence](SOURCE-CORRESPONDENCE.md)
and the applicable component delivery notes. This export adds no image, RF, USB
or hardware qualification.
