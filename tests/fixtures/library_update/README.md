# Real ZIM fixtures

`base.zim` and `target.zim` are real compressed archives generated with libzim 3.13.0. Original test content is dedicated to CC0-1.0: one HTML page and twenty deterministic incompressible binary assets. The target changes the visible page from `Library revision 0` to `Library revision 1`.

Generation: install optional `libzim==3.13.0`, add `tests` to Python's path, and call `library_update_support.create_zim(Path('base.zim'), 0)` and the corresponding revision-1 call. Production adapters never import this helper or libzim. The content is deterministic; libzim assigns archive UUIDs, so regenerated archive bytes/hashes can differ. `fixtures.json` records the hashes of the checked-in copies.

These are controlled integration fixtures, not independently published historical editions or evidence for multi-gigabyte performance.
