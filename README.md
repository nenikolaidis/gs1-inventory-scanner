# Inventory_Scanner
Absolutely 👍
Below is the **final version exactly as a `README.md` file**.
You can **copy–paste this directly** into a file named `README.md` in your project root.

---

````markdown
# Inventory Scanner (GS1)

A desktop inventory scanning application built with **Python**, **Tkinter**, and **SQLite**.

The app:
- Parses GS1 barcodes (human-readable and raw scanner input)
- Allows manual entry of SKU and storage location
- Saves all data to a local SQLite database
- Supports searching and viewing stored records
- Prints **PDF labels with scannable Code128 barcodes**

---

## Requirements

### 1. Python
- **Python 3.10 or newer** is recommended

Check your version:
```bash
python3 --version
````

---

### 2. Python Libraries

The only external library required is **ReportLab** (used for PDF and barcode printing).

Install it with:

```bash
python3 -m pip install reportlab
```

> **Important (macOS users)**
> If `pip` is not found, always use:
>
> ```bash
> python3 -m pip install reportlab
> ```

---

### 3. GUI Library (Tkinter)

Tkinter is usually included with Python.

#### Linux only

If Tkinter is missing:

```bash
sudo apt install python3-tk        # Ubuntu / Debian
sudo dnf install python3-tkinter   # Fedora
```

---

### 4. Printing Support (System Tools)

Printing uses your operating system:

| OS      | Tool used    | Notes                |
| ------- | ------------ | -------------------- |
| macOS   | `lp`         | Installed by default |
| Linux   | `lpr`        | Requires CUPS        |
| Windows | System print | Uses default printer |

---

## Project Structure

Example layout:

```text
inventory_scanner/
├── main.py
├── gui.py
├── barcode_parser.py
├── database.py
├── models.py
├── utils.py
├── print_label.py
├── inventory.db        # created automatically
├── README.md
└── tests/
    └── test_parsing_50cases.py
```

---

## Setup

From the project directory:

```bash
python3 -m pip install reportlab
```

---

## Run the Application

### macOS / Linux

```bash
python3 main.py
```

### Windows

```powershell
py main.py
```

The **GUI will open automatically**.

---

## How to Use

1. **Scan or paste** a barcode into the input field
2. Click **Parse**
3. Fill in manual fields:

   * SKU (5–6 alphanumeric characters)
   * Warehouse
   * Aisle
   * Position
   * Shelf
4. Click **Save Record**
   → Data is stored in `inventory.db`
5. Click **Search** to:

   * Find saved records
   * View full record details
   * Load a record back into the form
6. Click **Print** to:

   * Generate a PDF label
   * Print a **Code128 barcode**

---

## Supported Barcode Formats

### Human-Readable GS1

```
(02)38033432662426(11)250319(10)0090167063(00)380334329001623191(37)000360
```

### Raw Scanner Output

```
0238033432662426112503191000901670630038033432900162319137000360
```

---

## Supported GS1 Application Identifiers

| AI  | Description              |
| --- | ------------------------ |
| 00  | SSCC (18 digits)         |
| 01  | GTIN (14 digits)         |
| 02  | Content GTIN             |
| 10  | Batch / Lot              |
| 11  | Production Date (YYMMDD) |
| 21  | Serial Number            |
| 37  | Quantity                 |
| 240 | Additional Product ID    |
| 241 | Customer Part Number     |

> Raw barcodes without FNC1 separators are parsed using a **backtracking heuristic parser**.

---

## Database

* Database file: **`inventory.db`**
* Automatically created on first run
* Stores:

  * Parsed GS1 fields
  * Raw barcode
  * SKU and storage location
  * Creation timestamp

---

## Testing

Run the parser tests:

```bash
python3 tests/test_parsing_50cases.py
```

Expected result:

```
passed: 50
failed: 0
```

---

## Troubleshooting

### `pip: command not found`

Use:

```bash
python3 -m pip install reportlab
```

### Printing fails

* Open the generated PDF manually and print
* Ensure CUPS tools are installed on Linux/macOS

---

## Future Improvements

* GS1 FNC1 (ASCII 29) separator support
* Advanced search filters
* Print directly from search results
* User authentication / roles

---

## License

Internal / Private project (adjust as needed)

```

---

If you want next:
- `requirements.txt`
- installer script (`setup.sh`)
- Windows `.exe` build (PyInstaller)

Just tell me.
```
