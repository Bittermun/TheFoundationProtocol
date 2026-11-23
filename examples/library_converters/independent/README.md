# Offline checklist converter

This standard-library Python converter turns a CSV checklist into a searchable
text page. It derives the page title from the filename and keeps items in CSV
row order. The page shows each item with its status and any notes.

Save each checklist as UTF-8 CSV with the exact header `item,status,notes`.
Use `Open`, `In progress`, or `Done` for status. Status is case-insensitive and
the notes field can be empty. Put commas and line breaks inside quoted fields.

From this directory, preview either document locally with Python.

```sh
python checklist_converter.py documents/reading-room.csv
python checklist_converter.py documents/community-workshop.csv
```

Use the recipe and the [TFP converter interface](../../../docs/library-converter.md)
to build a new ZIM in the same directory.

```sh
tfp library-build recipe.json --input-dir documents --converter-file checklist_converter.py --out volunteer-checklists.zim
```

Search for `lantern inventory` under **Reading Room** or `ceramic kiln` under
**Community Workshop**.
