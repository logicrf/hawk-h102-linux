# Repository guidance

This branch is the English H102 integration-source distribution. Preserve pinned input identities, upstream notices and SOURCE-MAP.json. User documentation describes executable tasks and actual support limits.

Develop functional changes in the internal Chinese main branch, then review and translate a fixed source set into github-en. GitHub main follows the same English commit and remains private unless explicitly approved for public release. Never mirror internal history.

Run scripts/check_distribution.py and the relevant offline tests before synchronization. Regenerate SOURCE-FILES.json only for intentionally reviewed changes. An English packaging change does not qualify a new image, hardware revision or RF/data capability. Historical recipes keep their original checks and may require separate original-source objects and input receipts.
