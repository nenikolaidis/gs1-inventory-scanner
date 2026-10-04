# GS1 Inventory Scanner

[![CI](https://github.com/nenikolaidis/gs1-inventory-scanner/actions/workflows/ci.yml/badge.svg)](https://github.com/nenikolaidis/gs1-inventory-scanner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE.md)

A small desktop app for warehouses: scan a GS1 barcode (pallet label, carton,
product), add the SKU and storage location, and keep everything in a local
SQLite database. It can also print the data back out as a PDF label with real
GS1-128 barcodes.

Built with Python, Tkinter, [biip](https://github.com/jodal/biip) and
[ReportLab](https://www.reportlab.com/opensource/).

## Features

- Reads GS1 data in every common form:
  - human-readable: `(01)03012345678902(10)LOT1(37)12`
  - raw with FNC1/GS separators, with or without a symbology prefix like `]C1`
  - raw **without** separators, which is what most keyboard-wedge scanners
    send (see [below](#barcodes-without-separators))
  - plain EAN-13 / UPC / GTIN numbers
- Validates check digits, dates and field formats, and shows warnings instead
  of silently storing bad data.
- Stores records with SKU, warehouse, aisle, position and shelf; search, view,
  reload and delete them.
- Prints a PDF label with GS1-128 barcodes (split over several symbols when the
  data exceeds the 48-character GS1 limit) and opens it in your PDF viewer.

## Install

Requires Python 3.10 or newer with Tkinter (included with the python.org
installers; on Linux install `python3-tk` on Debian/Ubuntu or `python3-tkinter`
on Fedora).

```bash
git clone https://github.com/nenikolaidis/gs1-inventory-scanner.git
cd gs1-inventory-scanner
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install .
```

## Run

```bash
gs1-scanner                      # or: python -m gs1_scanner
gs1-scanner --db path/to/inventory.db
```

By default the database is kept in your user data folder:

| OS      | Location                                          |
| ------- | ------------------------------------------------- |
| macOS   | `~/Library/Application Support/gs1-scanner/`      |
| Windows | `%APPDATA%\gs1-scanner\`                          |
| Linux   | `~/.local/share/gs1-scanner/` (or `$XDG_DATA_HOME`) |

Set `GS1_SCANNER_HOME` to use a different folder. Databases created by older
versions of the app are upgraded automatically when opened.

## Usage

1. Scan a barcode into the top field. Most scanners send Enter afterwards,
   which parses it and moves to the SKU field.
2. Check the parsed values and any warnings.
3. Fill in SKU (5–6 letters/digits) and location, then press **Save Record**
   (or Enter in the Shelf field).
4. **Search Records…** finds records by any barcode value, SKU or location.
   Double-click a row to see it, or load it back into the form.
5. **Print Label…** creates a PDF label and opens it so you can print it.

## Barcodes without separators

In GS1 barcodes, variable-length fields such as lot (10) or serial number (21)
end with an invisible FNC1 character. Most scanners in keyboard mode drop that
character, so `10ABC2112` could mean lot `ABC2112`, or lot `ABC` followed by
serial `12`.

For this kind of input the app uses its own parser
([`raw_parser.py`](src/gs1_scanner/raw_parser.py)). It finds every way the
input can be split using the AIs below, discards splits that break GS1 rules
(e.g. a non-numeric quantity or month 13), and prefers splits with valid check
digits and more fields. If two readings are equally plausible, it uses one and
warns you, showing the other.

| AI  | Meaning              | AI  | Meaning                 |
| --- | -------------------- | --- | ----------------------- |
| 00  | SSCC                 | 17  | Expiry date             |
| 01  | GTIN                 | 21  | Serial number           |
| 02  | Content GTIN         | 37  | Quantity                |
| 10  | Batch / lot          | 240 | Additional product ID   |
| 11  | Production date      | 241 | Customer part number    |
| 15  | Best before date     |     |                         |

Barcodes with separators or in human-readable form can use any GS1 AI.

To avoid the ambiguity entirely, configure your scanner to send the FNC1/GS
character (ASCII 29) or a symbology identifier prefix (`]C1`).

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

Project layout:

```text
src/gs1_scanner/
├── gs1.py         # parsing front end: chooses biip or the raw parser
├── raw_parser.py  # parser for raw input without FNC1 separators
├── ais.py         # GS1 AI metadata, validation, DB column mapping
├── models.py      # InventoryRecord
├── storage.py     # SQLite storage and schema upgrades
├── labels.py      # GS1-128 PDF labels
├── service.py     # application logic used by the GUI
├── gui.py         # Tkinter interface
└── app.py         # command-line entry point
```

## License

[MIT](LICENSE.md)
