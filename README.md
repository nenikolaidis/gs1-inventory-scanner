# GS1 Scanner

Scan GS1 pallet and carton labels on any device, track stock by location, lot
and expiry date, and print GS1-128 labels.

GS1 Scanner turns handheld scanners, tablets, phones and desktop PCs into a
warehouse stock tool. Operators scan a shelf label, then pallets: the app reads
GTIN, lot, expiry date, SSCC and quantity, including from scanners that drop the
FNC1 separators most tools rely on. Every receipt, pick and move updates the
stock, oldest expiry first; stock counts correct it; and every change is
recorded with who made it. It works with hardware scanners or a phone camera,
keeps working in Wi-Fi dead spots, and prints to A4 or Zebra label printers.
It runs on the company's own server, so the data stays with the company.

© 2026 Nearchos Nikolaidis. All rights reserved. See [LICENSE.md](LICENSE.md).

---

## What you need to run it

### To try it on one computer

| Requirement | Version | Why |
| --- | --- | --- |
| Python | 3.10 or newer | Runs the server |
| Node.js | 20 or newer | Builds the web interface (only needed once, when installing) |
| A web browser | Any recent Chrome, Edge, Safari or Firefox | The app's interface |

The Python libraries (FastAPI, SQLAlchemy, biip, ReportLab and others) are
installed automatically by `pip`. The database is a single SQLite file that
is created automatically, so nothing else needs installing.

### To run it for a team

| Requirement | Why |
| --- | --- |
| Docker with Docker Compose | Runs the app and its PostgreSQL database with one command |
| A server or always-on PC on the warehouse network | So every device can reach it |
| An HTTPS reverse proxy (Caddy, nginx or Traefik) | Encrypts logins; phones also require HTTPS for camera scanning, installing the app and offline use |

### Hardware

- **Barcode scanners** in keyboard mode ("keyboard wedge") that send Enter
  after each scan. This is the default on most handheld and USB scanners.
  Ideally, configure them to transmit the FNC1 character (ASCII 29) or the
  `]C1` prefix; the app works without it, but it is more reliable with it.
- **Or phones** with a camera, using the app's built-in camera scanner.
- **A printer** for labels, either:
  - an ordinary printer: shelf labels are laid out for A4 sheets of 2 × 7
    labels (99.1 × 38.1 mm), pallet labels on A4; or
  - a **Zebra (or ZPL-compatible) thermal printer**: 4×6" or 100×150 mm pallet
    labels and 4×2" shelf labels, at 203, 300 or 600 dpi. On the network, the
    app can print to it directly.

---

## How to run it

### Trial on one computer

```bash
git clone https://github.com/nenikolaidis/gs1-inventory-scanner.git
cd gs1-inventory-scanner
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
cd web && npm ci && npm run build && cd ..
pip install .
gs1-scanner serve
```

Open http://127.0.0.1:8000 and create the first admin account.

For phones and handhelds on the same network, start it with
`gs1-scanner serve --host 0.0.0.0` and open `http://<computer's IP>:8000` on
the device.

### For a team (Docker + PostgreSQL)

```bash
cp .env.example .env        # set POSTGRES_PASSWORD (letters and digits)
docker compose up -d
```

The app runs on port 8000. Put it behind an HTTPS reverse proxy and set
`GS1_SCANNER_SECURE_COOKIES=true` in `.env`. Back up the database volume
regularly (for example with `pg_dump`).

### Settings

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `GS1_SCANNER_DATABASE_URL` | SQLite file in the user data folder | Database to use, e.g. `postgresql+psycopg://user:pw@host/db` |
| `GS1_SCANNER_HOME` | Platform user data folder | Where the default SQLite file is kept |
| `GS1_SCANNER_SECURE_COOKIES` | `false` | Set to `true` when served over HTTPS |
| `GS1_SCANNER_SESSION_DAYS` | `14` | How long a login lasts |
| `GS1_SCANNER_SKU_PATTERN` | `[A-Za-z0-9._-]{1,40}` | Rule SKUs must follow, e.g. `[A-Za-z0-9]{5,6}` |
| `GS1_SCANNER_EXPIRY_WARNING_DAYS` | `30` | Stock expiring within this many days is flagged |
| `GS1_SCANNER_ZEBRA_PRINTER` | (none) | Network label printer, `host` or `host:port` (default port 9100) |
| `GS1_SCANNER_LABEL_DPI` | `203` | Thermal printer resolution: `203`, `300` or `600` |
| `GS1_SCANNER_LABEL_SIZE` | `4x6` | Thermal pallet label size: `4x6` (inch) or `100x150` (mm) |

### Commands

```bash
gs1-scanner serve [--host 0.0.0.0] [--port 8000]   # start the server
gs1-scanner create-user NAME [--admin]             # add a user from the terminal
gs1-scanner import-legacy path/to/inventory.db     # import data from the old desktop version
gs1-scanner db upgrade                             # update the database structure
```

---

## What I built

The project started as a single-computer desktop app (Python and Tkinter) that
parsed GS1 barcodes and saved them to SQLite. I rebuilt it in three steps:
first I fixed the parser and turned the code into a proper Python package with
tests, then I turned it into a multi-user web application, and then I added
stock tracking, stock counts, thermal labels and phone support.

### 1. A reliable GS1 parser

GS1 barcodes pack several fields into one string, each starting with an
Application Identifier (AI): `(01)` is the GTIN, `(10)` the lot, `(17)` the
expiry date, `(37)` the quantity, and so on. Variable-length fields like the lot
end with an invisible FNC1 character, but most scanners in keyboard mode drop
it. Then `10ABC2112` could be lot `ABC2112`, or lot `ABC` followed by serial
number `12`.

- **Barcodes with separators** are parsed with
  [biip](https://github.com/jodal/biip), an established GS1 library that knows
  every official AI.
- **Human-readable barcodes** like `(01)…(10)…` are split by my own code and
  each field is checked against biip's GS1 rules. I found that biip's own
  human-readable parser silently cuts values at punctuation (lot `A-B` became
  `A`), which would have stored wrong data without any warning.
- **Barcodes without separators** go through my own parser
  ([`raw_parser.py`](src/gs1_scanner/raw_parser.py)). It lists every possible
  way to split the input, throws out splits that break GS1 rules (a quantity
  with letters, month 13, a wrong check digit), and ranks the rest. If two
  readings are equally likely, it picks one **and warns the user**, showing the
  other, instead of silently guessing.
- **Validation:** check digits on GTINs and SSCCs, real calendar dates, and
  field formats. Problems are shown as warnings, never hidden.
- **Plain EAN-13/UPC product barcodes** are recognised as GTINs.

### 2. The scanning workflow

The scan screen is designed so an operator never has to touch the keyboard:

- **One input for everything.** Scanning a shelf label sets the current
  location; scanning a pallet label records it at that location. The location
  stays set for the next pallets.
- **Quick save.** Clean scans are saved immediately with a beep and a
  vibration. Scans with warnings wait for the operator to check and confirm.
- **Undo.** Operators can undo their own scans for 10 minutes; admins can
  delete any scan.
- **Product learning.** The first time someone enters a SKU for a new GTIN, the
  app remembers it and fills it in automatically from then on.

### 3. History, export and labels

- **Search and filters** across SKU, GTIN, SSCC, lot, serial number, location
  and dates.
- **CSV export** for Excel or an ERP system, protected against spreadsheet
  formula injection (scanned text is never executed as a formula).
- **GS1-128 labels** with real FNC1 separators, so other systems can scan them.
  Data longer than the GS1 limit of 48 characters is split across several
  barcodes, as on real logistics labels.
- **Shelf location labels** printed on standard A4 label sheets.

### 4. Stock tracking

- **Stock is calculated from movements**, never stored as a running total:
  every receipt, pick, move and correction is a signed movement, so the stock
  always matches its history. Stock is tracked per location, GTIN, lot, expiry
  date and pallet (SSCC).
- **Scan modes** on one screen: *Receive* (into a location), *Pick* (out of
  stock), *Move* (scan the pallet, then the destination), *Count* and *Find*
  (where is this item, or what is on this shelf).
- **First expiry, first out:** picks take the stock that expires first.
- **Pallets by SSCC:** scanning only a pallet's SSCC moves or picks the whole
  pallet; the app knows what is on it and where it is.
- **Clear errors:** "Not in stock at B1. Found at: A1", or "In stock at several
  locations (A1, A2). Scan the location first", instead of guessing.
- **Undo** reverts a scan's effect on stock.

### 5. Stock counts, corrections and expiry

- **Stock counts:** an operator scans a shelf, then everything on it. The
  review shows expected, counted and the difference per item; anything not
  counted is treated as missing. An admin applies the count, which records
  each difference as a correction labelled with the count number.
- **Manual corrections** by admins, with a required reason.
- **Expiry warnings** when receiving expired or soon-expiring stock, and a
  banner on the Stock page with what is expired or expiring.
- **Activity log:** every change to products, locations, users and stock
  corrections, deleted scans and logins, with what changed (passwords are never
  recorded).

### 6. Thermal labels and printing

- **Zebra (ZPL) labels** at 203/300/600 dpi: 4×6" pallet labels laid out like
  standard logistics labels, and 4×2" shelf labels.
- **Exact barcodes:** the app computes each GS1-128 symbol itself and sends it
  to the printer with explicit code sets and FNC1, rather than relying on the
  printer's automatic mode. Bars are kept at least 2 dots wide; long data is
  split over more barcodes rather than printed too thin to scan.
- **Direct printing** to a network printer, from a scan or a set of locations.
- **Verified:** I decoded the generated PDF and ZPL labels with the zxing
  barcode reader to confirm they read back as valid GS1-128 with the right data.

### 7. Phones: camera, install, offline

- **Camera scanning** with zxing compiled to WebAssembly, bundled with the app
  (no internet needed). It passes the barcode's raw data and symbology
  identifier to the server, so camera scans are never ambiguous.
- **Installable app** (Progressive Web App) with its own icon; it starts
  without a connection.
- **Offline scanning:** in a Wi-Fi dead spot, scans are queued on the device and
  uploaded when the connection returns. Each scan has a unique reference, so a
  retried upload is never saved twice. Scans the server refuses (e.g. not
  enough stock) are shown on the device to fix or discard.

### 8. Users and security

- **Two roles:** operators scan, search and print; admins also manage products,
  locations and users.
- **Passwords** are hashed with scrypt; login sessions are stored server-side
  and sent as secure, HttpOnly cookies.
- **Protection** against cross-site request forgery and against password
  guessing (repeated failed logins are blocked for a few minutes).
- **First-run setup:** the first admin account is created in the browser.

### 9. Architecture

```text
 Handheld scanner / phone / tablet / desktop browser
                  │
       React + TypeScript web interface
                  │  JSON API
       FastAPI server (Python)
        ├── GS1 parsing and validation
        ├── PDF label generation (ReportLab)
        └── SQLAlchemy + Alembic migrations
                  │
       SQLite (one computer)  or  PostgreSQL (team)
```

- **Backend:** FastAPI (Python), with the parser and label code as separate,
  independently tested modules. The server also serves the web interface, so
  a deployment is a single process.
- **Database:** SQLAlchemy models with Alembic migrations, which upgrade the
  database automatically when a new version starts. SQLite and PostgreSQL are
  both supported.
- **Frontend:** React and TypeScript, built with Vite and kept to three
  libraries (React, React DOM and the zxing barcode reader, which only loads
  when the camera is used). It adapts to phones (bottom tab bar, tables shown
  as cards) and desktops, and supports light and dark mode.
- **Deployment:** a Dockerfile and Docker Compose file that run the app with
  PostgreSQL.
- **Migration from the old version:** `gs1-scanner import-legacy` copies
  records from the original desktop app's database without modifying it.

### 10. Quality

- **150 automated tests** covering the parser (including every bug found
  in the original version), stock rules, counts, permissions, the activity
  log, labels and ZPL, printing, offline retries, CSV export, data import and
  database migrations.
- **Continuous integration** on GitHub Actions on every push:
  - the tests on Python 3.10 to 3.13
  - on Linux, macOS and Windows
  - against PostgreSQL
  - the web build
  - a Docker build and start-up check
- **Code style** checked with Ruff (Python) and the TypeScript compiler.

---

## Development

```bash
pip install -e ".[dev]"
pytest                             # run the tests
ruff check . && ruff format --check .

gs1-scanner serve                  # API on port 8000
cd web && npm ci && npm run dev    # interface with live reload on port 5173
```

```text
src/gs1_scanner/
├── gs1.py, raw_parser.py, ais.py   # GS1 parsing and validation
├── labels.py                       # GS1-128 and shelf label PDFs
├── cli.py                          # the gs1-scanner command
└── server/                         # API, database models, migrations
web/                                # React + TypeScript interface
tests/                              # automated tests
```

---

## License

© 2026 Nearchos Nikolaidis. All rights reserved.

This code may not be used, copied, modified or distributed without written
permission. See [LICENSE.md](LICENSE.md). For licensing or purchase enquiries,
contact me through [GitHub](https://github.com/nenikolaidis).
