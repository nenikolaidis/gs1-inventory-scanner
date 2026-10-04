# GS1 Scanner

Scan GS1 pallet and carton labels on any device, record where stock goes, and
print GS1-128 labels.

GS1 Scanner turns handheld scanners, tablets, phones and desktop PCs into a
warehouse receiving and put-away tool. You scan a shelf label to set the
location, then scan pallets: the app reads GTIN, lot, expiry date, SSCC and
quantity, including from scanners that drop the FNC1 separators most tools rely
on, and records who scanned what, where and when. The team can search and
export the history and print GS1-128 labels. It runs on the company's own
server, so the data stays with the company.

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
| An HTTPS reverse proxy (Caddy, nginx or Traefik) | Encrypts logins between devices and the server |

### Hardware

- **Barcode scanners** in keyboard mode ("keyboard wedge") that send Enter
  after each scan. This is the default on most handheld and USB scanners.
  Ideally, configure them to transmit the FNC1 character (ASCII 29) or the
  `]C1` prefix; the app works without it, but it is more reliable with it.
- **A printer** for labels. Shelf labels are laid out for A4 sheets of
  2 × 7 labels (99.1 × 38.1 mm).

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
parsed GS1 barcodes and saved them to SQLite. I rebuilt it in two steps: first
I fixed the parser and turned the code into a proper Python package with tests,
then I turned it into a multi-user web application.

### 1. A reliable GS1 parser

GS1 barcodes pack several fields into one string, each starting with an
Application Identifier (AI): `(01)` is the GTIN, `(10)` the lot, `(17)` the
expiry date, `(37)` the quantity, and so on. Variable-length fields like the lot
end with an invisible FNC1 character, but most scanners in keyboard mode drop
it. Then `10ABC2112` could be lot `ABC2112`, or lot `ABC` followed by serial
number `12`.

- **Barcodes with separators or in human-readable form** are parsed with
  [biip](https://github.com/jodal/biip), an established GS1 library that knows
  every official AI.
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

### 4. Users and security

- **Two roles:** operators scan, search and print; admins also manage products,
  locations and users.
- **Passwords** are hashed with scrypt; login sessions are stored server-side
  and sent as secure, HttpOnly cookies.
- **Protection** against cross-site request forgery and against password
  guessing (repeated failed logins are blocked for a few minutes).
- **First-run setup:** the first admin account is created in the browser.

### 5. Architecture

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
- **Frontend:** React and TypeScript, built with Vite and kept to two
  libraries (React and React DOM). It adapts to phones (bottom tab bar, tables
  shown as cards) and desktops, and supports light and dark mode.
- **Deployment:** a Dockerfile and Docker Compose file that run the app with
  PostgreSQL.
- **Migration from the old version:** `gs1-scanner import-legacy` copies
  records from the original desktop app's database without modifying it.

### 6. Quality

- **100 automated tests** covering the parser (including every bug found in
  the original version), the API, permissions, labels, CSV export and data
  import.
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
