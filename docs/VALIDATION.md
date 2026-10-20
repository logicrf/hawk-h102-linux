# English source-package verification

Verified on 20 October 2026 on Ubuntu 22.04 x86_64 with Python 3.10 and libiio 0.23 development/runtime files.

| Check | Result / scope |
|---|---|
| SD deployment, lock, network recovery, IIO broker and control protocol tests | 47 passed, plus 27 unittest subtests; temporary files/local fixtures only |
| C++/Python IIO examples and native fault cleanup | 16 passed; one optional external legacy GUI-runtime test skipped because that pinned input was not supplied |
| Original translated source review | Python executable structure and nonlocalized constants checked; localized strings listed separately; C/C++/C# executable tokens unchanged |
| Source package | Exact file set, SHA-256, English text, Python syntax, local import closure and documentation links checked by check_distribution.py |
| Device-tree reference | Decompiled from the SHA-pinned DTB. Recompilation is not byte-identical; configuration structure is checked separately |
| Windows generator execution | NOT_RUN in this packaging update; matching Windows SDK inputs are required |
| Full kernel/image reconstruction | NOT_RUN; original fixed inputs and applicable vendor/source packages are separate |
| SD writes, boot, IQ/RF, USB or live service installation | NOT_RUN in this packaging update |

The first IIO-example collection detected missing local helper files. The corrected package includes the previously reviewed English helpers, pins their actual local hashes and retains original hashes separately. It does not alter the installed board SDK or firmware requirements. The optional runtime test now requires an explicit environment path rather than guessing an internal workstation path.

This is a source-delivery verification result. Existing H102 1.2.0 hardware claims remain limited to their original exact image and test windows. Missing inputs and skipped tests are not successful new device qualification.
