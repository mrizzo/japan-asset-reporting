# Japan Asset Reporting (財産債務調書 / 国外財産調書)

Fills four NTA forms from two CSV files and outputs print-ready PDFs:

| File | Form | Description |
|------|------|-------------|
| `FA6103-filled.pdf` | FA6103 | 財産債務調書（明細） |
| `FA6003-filled.pdf` | FA6003 | 財産債務調書合計表 |
| `FA5003-detail-filled.pdf` | FA5003 | 国外財産調書（明細） |
| `FA5003-summary-filled.pdf` | FA5003合計表 | 国外財産調書合計表 |

Assets with `fa6103_group=overseas` appear on the FA6103 as a single 国外財産 line and are expanded to individual rows on the FA5003 detail form.

## Requirements

- Python 3.9+
- A CJK font — Arial Unicode (`/Library/Fonts/Arial Unicode.ttf`, included with Microsoft Office on macOS) or Noto Sans CJK (`sudo apt install fonts-noto-cjk` on Linux)

Install Python dependencies:

```bash
make install
# or: pip3 install -r requirements.txt
```

Verify your setup:

```bash
make check
```

## Usage

1. Copy the example CSVs and fill in your data:

```bash
cp assets.csv.example assets.csv
cp config.csv.example config.csv
```

2. Run:

```bash
make run
# or: python3 fill_forms.py
# or: python3 fill_forms.py my_assets.csv my_config.csv
```

Output PDFs are written to `output/`.

## CSV format

**config.csv** — personal info and FX rates. One `key,value` row per field. Add `fx_USD`, `fx_EUR`, etc. for any foreign currencies in your assets. See `config.csv.example`.

**assets.csv** — one row per account or asset. See `assets.csv.example` for all columns.

The `fa6103_group` column controls how rows are grouped on the detail form. All rows with `fa6103_group=overseas` are collapsed into a single 国外財産 line pointing to the FA5003.

Supported `asset_type` values: `land`, `building`, `cash`, `savings`, `listed_stock`, `loan_receivable`, `vehicle`, `crypto`, `pension`, `other`.

## Blank forms

The blank PDF templates in `asset-report-forms/` are the **令和7年分 (2025 tax year, filed 2026)** versions downloaded from the NTA website.

**Check for updated forms each year before filing.** NTA occasionally revises form layouts between years. Download the latest blanks from:

> https://www.nta.go.jp/taxes/tetsuzuki/shinsei/annai/hotei/annai/zaisan.htm

If the layout changes significantly, the coordinate constants in `fill_forms.py` will need recalibration.

## FX rate

One rate per currency, supplied in `config.csv`. The rate used should be consistent with your US federal return (e.g., IRS TTM for the tax year). Japan does not mandate a specific rate for this form; consistency year-to-year is what matters.
