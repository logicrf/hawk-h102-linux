# Maintaining the English distribution

Develop and commit in Chinese on the internal Gitea main branch. Review a fixed input commit, then update Gitea github-en with English source comments, user messages, documentation and commit messages. GitHub main receives the same reviewed commit and remains private until a separate public-release decision.

Do not mirror all internal branches or research history. Export only the reviewed file set and preserve SOURCE-BASE.json, SOURCE-MAP.json, component notices and original/translated hashes. Existing image and installed-helper hashes must not be replaced with translated hashes to make admission appear compatible.

Refresh SOURCE-FILES.json after intentional changes, run the distribution checker and relevant offline tests, then verify the exact remote commit and files from independent clones. Do not claim full image reconstruction, hardware compatibility or new RF qualification from a language/source packaging update.

The released 1.2.0 image remains separate from this toolkit's source delivery version. Full upstream source, original reconstruction inputs, vendor rights and the optional control add-ons are tracked individually.
