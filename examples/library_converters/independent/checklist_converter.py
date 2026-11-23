"""Convert a UTF-8 CSV checklist to a title and searchable plain text."""

import argparse
import csv
import io
from pathlib import Path
import sys


TFP_CONVERTER_API = 1

MAX_DOCUMENT_BYTES = 1024 * 1024
HEADER = ["item", "status", "notes"]
STATUSES = {"open": "Open", "in progress": "In progress", "done": "Done"}


def convert(document: bytes, *, filename: str) -> tuple[str, str]:
    """Read one checklist and render each item, status, and optional notes."""
    if len(document) > MAX_DOCUMENT_BYTES:
        raise ValueError("CSV input exceeds 1 MiB")
    if not filename.lower().endswith(".csv"):
        raise ValueError("Checklist filename must end in .csv")
    stem = filename[:-4].translate(str.maketrans("-_.", "   "))
    title = " ".join(stem.split()).title()
    if not 1 <= len(title) <= 120:
        raise ValueError("Checklist title must have 1 to 120 characters")

    try:
        source = document.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Checklist must be UTF-8") from error
    if "\x00" in source:
        raise ValueError("Checklist contains a NUL character")

    rows = csv.reader(io.StringIO(source, newline=""), strict=True)
    paragraphs = []
    body_bytes = 0
    try:
        if next(rows, None) != HEADER:
            raise ValueError("CSV header must be item,status,notes")
        for row in rows:
            if not row:
                continue
            if len(row) != len(HEADER):
                raise ValueError(f"CSV line {rows.line_num} must have three fields")
            item, status, notes = (field.strip() for field in row)
            if not item:
                raise ValueError(f"CSV line {rows.line_num} has an empty item")
            status_label = STATUSES.get(status.casefold())
            if status_label is None:
                raise ValueError(
                    f"CSV line {rows.line_num} status must be Open, In progress, or Done"
                )
            paragraph = f"{item} [{status_label}]"
            if notes:
                paragraph += f"\nNotes: {notes}"
            body_bytes += len(paragraph.encode("utf-8"))
            if paragraphs:
                body_bytes += 2  # Blank line between checklist items.
            if body_bytes > MAX_DOCUMENT_BYTES:
                raise ValueError("Checklist body exceeds 1 MiB of UTF-8")
            paragraphs.append(paragraph)
    except csv.Error as error:
        raise ValueError(f"Malformed CSV near line {rows.line_num}: {error}") from error

    if not paragraphs:
        raise ValueError("CSV must contain at least one checklist item")
    return title, "\n\n".join(paragraphs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path, help="Path to one checklist CSV")
    path = parser.parse_args().document
    try:
        with path.open("rb") as source:
            title, body = convert(source.read(MAX_DOCUMENT_BYTES + 1), filename=path.name)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{path.name}: {error}\n")
    sys.stdout.buffer.write(f"{title}\n\n{body}\n".encode("utf-8"))


if __name__ == "__main__":
    main()
