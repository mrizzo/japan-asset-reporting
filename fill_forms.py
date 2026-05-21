#!/usr/bin/env python3
"""
Japan Tax Form Filler
Fills FA6103 (財産債務調書) and FA6003 (財産債務調書合計表) from CSV inputs.

Usage:
    python fill_forms.py                           # assets.csv + config.csv in same dir
    python fill_forms.py assets.csv config.csv     # explicit paths

Output: output/FA6103-filled.pdf and output/FA6003-filled.pdf
"""

import csv
import sys
from pathlib import Path
from io import BytesIO
from collections import defaultdict, OrderedDict

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter

# ── Paths ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
ALR_DIR      = SCRIPT_DIR / "asset-report-forms" / "ALR"
FA6103_BLANK = ALR_DIR / "FA6103-zaisan-saimu-detail-FILLABLE.pdf"
FA6003_BLANK = ALR_DIR / "FA6003-zaisan-saimu-goukei-hyo-FILLABLE.pdf"
FONT_NAME   = "JP"
_FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",           # macOS + Office
    "/System/Library/Fonts/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",  # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
FONT_PATH = next((p for p in _FONT_CANDIDATES if Path(p).exists()), None)
if FONT_PATH is None:
    raise SystemExit(
        "No CJK font found. Install Arial Unicode (via Office) or Noto Sans CJK.\n"
        "On Linux: sudo apt install fonts-noto-cjk"
    )

# ── Coordinate system ──────────────────────────────────────────────────────────
# Source coordinates come from the filled forms (595.28 × 841.89 A4).
# The blank templates are 649.50 × 814.79 with a different origin.
# Affine transform derived from matching pre-printed anchor labels:
#   x_blank = A * x_filled + C_X
#   y_blank = A * y_filled + B_Y   (pdfplumber top-origin)
# Coefficients measured from 令和 and 財産債務 anchor positions.

BLANK_W, BLANK_H = 649.50, 814.79

A      =  0.992290   # uniform scale
C_X    =  30.2563    # x offset
B_Y    = -10.5213    # y offset
SINK   =  10.0       # extra shift downward in pdfplumber px (tune ±2 if needed)

def y(top):
    """filled-form pdfplumber y → reportlab y on blank page."""
    return BLANK_H - (A * top + B_Y + SINK)

def x(left):
    """filled-form pdfplumber x → blank page x (absolute position)."""
    return A * left + C_X

def d(delta):
    """Scale a spacing/delta — no offset, just scale."""
    return A * delta

# ── Asset type config ──────────────────────────────────────────────────────────
# Maps asset_type → (FA6003 line, Japanese label for FA6103, default use code)

ASSET_CFG = {
    # Left column  (○1–○14)
    "land":              ("1",  "土地",               "投"),
    "building":          ("2",  "建物",               "居"),
    "forest":            ("3",  "山林",               "投"),
    "cash":              ("4",  "現金",               "生"),
    "savings":           ("5",  "預貯金",             "生"),
    "listed_stock":      ("6",  "上場株式",           "投"),
    "unlisted_stock":    ("7",  "非上場株式",         "投"),
    "bond":              ("8",  "公社債",             "投"),
    "investment_trust":  ("8",  "投資信託",           "投"),
    "loan_receivable":   ("13", "貸付金",             "投"),
    "accrued_income":    ("14", "未収入金",           "投"),
    # Right column (○15–○25)
    "art":               ("15", "書画骨董",           "投"),
    "precious_metal":    ("16", "貴金属",             "投"),
    "vehicle":           ("17", "動産",               "自"),
    "life_insurance":    ("18", "保険契約権利",       "生"),
    "crypto":            ("24", "暗号資産",           "投"),
    "pension":           ("25", "その他の財産",       "投"),
    "other":             ("25", "その他の財産",       "投"),
}

USE_CODES = {
    "residential": "居", "living": "生", "personal": "自",
    "investment":  "投", "business": "事",
}

# ── FA6103 coordinates (derived from zaisan_saimu_detail-filled.pdf) ──────────

FA6103_HDR = {
    "year_x":    x(179.4),  "year_y":    y(102.8), "year_dx":   d(14.5),
    "address_x": x(241.4),  "address_y": y(125.9),
    "name_x":    x(241.4),  "name_y":    y(179.8),
    "mynum_x":   x(242.5),  "mynum_y":   y(209.7), "mynum_dx":  d(14.2),
    "phone1_x":  x(435.6),  "phone_y":   y(215.6),
    "phone2_x":  x(478.0),
    "phone3_x":  x(519.0),
}

FA6103_ROW_Y0  = y(254.1)      # first row text baseline
FA6103_ROW_DY  = 24.05 * A    # row spacing scaled to blank page
FA6103_AMT_DY  = -10.1 * A    # amount offset scaled

FA6103_COL = {
    "type":     x(59.2),
    "kind":     x(111.5),
    "use":      x(195.7),
    "location": x(224.4),
    "quantity": x(381.9),
    "amount":   x(424.0),
    "notes":    x(508.8),
}

FA6103_BOT = {
    "total_x":        x(424.5),  "total_y":        y(682.4),
    "exit_tax_x":     x(280.1),  "exit_tax_y":     y(688.9),
    "assets_total_x": x(192.3),  "assets_total_y": y(718.3),
    "debts_total_x":  x(442.5),  "debts_total_y":  y(718.0),
}

# ── FA6003 coordinates (derived from zaisan-saimu-filled.pdf) ─────────────────

FA6003_HDR = {
    "year_x":       x(195.1),  "year_y":       y(44.2),  "year_dx":    d(13.5),
    "postal_x":     x(103.6),  "postal_y":     y(69.9),  "postal_dx":  d(13.5),
    "postal_x2":    x(153.3),   # 4-digit group starts here (gap after hyphen on form)
    "mynum_x":      x(322.1),  "mynum_y":      y(68.9),  "mynum_dx":   d(13.9),
    "address_x":    x( 95.3),  "address_y":    y(96.3),
    "address2_x":   x( 95.3),  "address2_y":   y(111.7),
    "furigana_x":   x(322.1),  "furigana_y":   y(92.1),
    "name_x":       x(322.1),  "name_y":       y(117.9),
    "occupation_x": x(336.1),  "occupation_y": y(143.0),
    "phone1_x":     x(454.8),  "phone_y":      y(149.6),
    "phone2_x":     x(489.0),
    "phone3_x":     x(523.3),
    "dob_era_x":    x(313.7),  "dob_y":        y(164.0),
    "dob_year_x":   x(335.7),  "dob_dx":       d(13.3),
    "dob_mon_x":    x(370.8),
    "dob_day_x":    x(406.0),
}

# FA6003 value field positions {line_key: (x, reportlab_y)}
# Verified against filled reference form. Use fa6003_line in assets.csv to
# override for lines not listed here.
FA6003_POS = {
    "1":  (x(146.3), y(235.1)),   # 土地
    "2":  (x(146.3), y(256.8)),   # 建物
    "4":  (x(146.3), y(305.4)),   # 現金
    "5":  (x(146.3), y(327.7)),   # 預貯金
    "6":  (x(146.3), y(351.2)),   # 上場株式
    "13": (x(146.3), y(656.0)),   # 貸付金
    "17": (x(399.4), y(280.4)),   # 動産
    "24": (x(399.4), y(444.8)),   # 暗号資産 (estimated — verify against output)
    "25": (x(399.4), y(467.4)),   # その他
    "26": (x(399.4), y(491.7)),   # 国外財産合計
    "27": (x(399.4), y(514.7)),   # 財産の価額の合計額
    "28": (x(399.4), y(538.0)),   # 国外転出特例（エ）
    "29": (x(399.4), y(562.3)),   # 国外転出特例合計
    "33": (x(399.4), y(679.1)),   # 債務の金額の合計額
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def draw_spaced(c, x0, y, dx, text):
    """Draw text one character at a time with fixed spacing (for boxed fields)."""
    for i, ch in enumerate(str(text)):
        c.drawString(x0 + i * dx, y, ch)

def fmt(n):
    """Comma-formatted for PDF fields."""
    return f"{int(n):,}"

def fmt_jp(n):
    """Human display in 億/万 notation."""
    n = int(n)
    oku  = n // 100_000_000
    man  = (n % 100_000_000) // 10_000
    rest =  n % 10_000
    parts = []
    if oku:  parts.append(f"{oku}億")
    if man:  parts.append(f"{man}万")
    if rest or not parts: parts.append(str(rest))
    return "".join(parts)

def register_font():
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))

def to_jpy(row, fx_rates):
    amount = float(row["amount"])
    cur = row.get("currency", "JPY").upper().strip()
    if cur == "JPY":
        return int(amount)
    rate = fx_rates.get(cur)
    if rate is None:
        raise ValueError(f"No FX rate for '{cur}'. Add fx_{cur} to config.csv.")
    return int(amount * float(rate))

# ── CSV I/O ────────────────────────────────────────────────────────────────────

def read_config(path):
    cfg = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cfg[row["key"].strip()] = row["value"].strip()
    return cfg

def read_assets(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def extract_fx(cfg):
    return {k[3:]: v for k, v in cfg.items() if k.startswith("fx_") and k != "fx_source"}

# ── Data processing ────────────────────────────────────────────────────────────

def process_assets(raw, fx_rates):
    for row in raw:
        row["jpy_amount"] = to_jpy(row, fx_rates)
    return raw

def build_fa6103_rows(assets):
    """
    Group assets into FA6103 line items by fa6103_group.
    All rows with group='overseas' collapse into one 国外財産 line at the end.
    Returns (rows, overseas_total).
    """
    groups = OrderedDict()
    for a in assets:
        g = a.get("fa6103_group", "").strip() or a["asset_type"]
        groups.setdefault(g, []).append(a)

    rows = []
    overseas_total = 0

    for group, items in groups.items():
        if group == "overseas":
            overseas_total = sum(i["jpy_amount"] for i in items)
            continue

        total   = sum(i["jpy_amount"] for i in items)
        first   = items[0]
        atype   = first["asset_type"]
        _, ja, default_use = ASSET_CFG.get(atype, ("25", atype, "投"))

        use_raw = first.get("use", "").strip()
        use     = USE_CODES.get(use_raw, use_raw[:1] if use_raw else default_use)

        # Quantity: sum if all numeric, else concatenate with "/"
        qtys = [i.get("quantity", "").strip() for i in items if i.get("quantity", "").strip()]
        try:
            qty = str(sum(int(q) for q in qtys))
        except ValueError:
            qty = "/".join(dict.fromkeys(qtys))  # deduplicated join

        rows.append({
            "kind":       ja,
            "use":        use,
            "location":   first.get("location", "").strip(),
            "quantity":   qty,
            "amount_jpy": total,
            "notes":      first.get("notes", "").strip(),
            "asset_type": atype,
        })

    if overseas_total:
        rows.append({
            "kind":       "国外財産",
            "use":        "投",
            "location":   "米国等",
            "quantity":   "一式",
            "amount_jpy": overseas_total,
            "notes":      "国外財",
            "asset_type": "overseas",
        })

    return rows, overseas_total

def build_fa6003_totals(assets, overseas_total):
    """Sum domestic assets by FA6003 line number; add overseas and grand total."""
    totals = defaultdict(int)
    for a in assets:
        if a.get("fa6103_group", "").strip() == "overseas":
            continue
        explicit = a.get("fa6003_line", "").strip()
        line = explicit if explicit else ASSET_CFG.get(a["asset_type"], ("25", "", ""))[0]
        totals[line] += a["jpy_amount"]

    totals["26"] = overseas_total
    # Grand total = all domestic lines + overseas
    totals["27"] = sum(v for k, v in totals.items() if k not in ("27", "28", "29", "33"))
    totals["33"] = 0  # no debt
    return totals

# ── PDF overlay ────────────────────────────────────────────────────────────────

def make_overlay(draw_fn):
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(BLANK_W, BLANK_H))
    draw_fn(c)
    c.save()
    buf.seek(0)
    return buf

def apply_overlay(blank_path, overlay_buf):
    """Merge overlay onto page 1 of blank; pass through remaining pages."""
    reader  = PdfReader(str(blank_path))
    writer  = PdfWriter()
    overlay_page = PdfReader(overlay_buf).pages[0]

    for i, page in enumerate(reader.pages):
        if i == 0:
            page.merge_page(overlay_page)
        writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out

# ── FA6103 drawing ─────────────────────────────────────────────────────────────

def draw_fa6103(c, cfg, rows, overseas_total):
    h = FA6103_HDR

    # Header
    c.setFont(FONT_NAME, 9)
    draw_spaced(c, h["year_x"], h["year_y"], h["year_dx"], cfg.get("year", "07"))

    c.setFont(FONT_NAME, 7)
    c.drawString(h["address_x"], h["address_y"], cfg.get("address_1", ""))

    c.setFont(FONT_NAME, 8)
    c.drawString(h["name_x"], h["name_y"], cfg.get("name_katakana", ""))

    mn = cfg.get("my_number", "").replace(" ", "").replace("-", "")
    draw_spaced(c, h["mynum_x"], h["mynum_y"], h["mynum_dx"], mn)

    c.drawString(h["phone1_x"], h["phone_y"], cfg.get("phone_1", ""))
    c.drawString(h["phone2_x"], h["phone_y"], cfg.get("phone_2", ""))
    c.drawString(h["phone3_x"], h["phone_y"], cfg.get("phone_3", ""))

    # Data rows
    col = FA6103_COL
    for i, row in enumerate(rows):
        y_text = FA6103_ROW_Y0 - i * FA6103_ROW_DY
        y_amt  = y_text + FA6103_AMT_DY

        c.setFont(FONT_NAME, 7)
        c.drawString(col["type"],     y_text, "資産")
        c.drawString(col["kind"],     y_text, row["kind"])
        c.drawString(col["use"],      y_text, row["use"])
        c.drawString(col["location"], y_text, row["location"])
        c.drawString(col["quantity"], y_text, row["quantity"])
        if row.get("notes"):
            c.drawString(col["notes"], y_text, row["notes"])

        c.setFont(FONT_NAME, 8)
        c.drawString(col["amount"], y_amt, fmt(row["amount_jpy"]))

    # Bottom totals
    grand = sum(r["amount_jpy"] for r in rows)
    b = FA6103_BOT
    c.setFont(FONT_NAME, 8)
    c.drawString(b["total_x"],        b["total_y"],        fmt(grand))
    c.drawString(b["assets_total_x"], b["assets_total_y"], fmt(grand))
    c.drawString(b["debts_total_x"],  b["debts_total_y"],  "0")
    if overseas_total:
        c.drawString(b["exit_tax_x"], b["exit_tax_y"], fmt(overseas_total))

# ── FA6003 drawing ─────────────────────────────────────────────────────────────

def draw_fa6003(c, cfg, totals):
    h = FA6003_HDR

    # Year
    c.setFont(FONT_NAME, 9)
    draw_spaced(c, h["year_x"], h["year_y"], h["year_dx"], cfg.get("year", "07"))

    # Postal code: 3-digit group, then gap (hyphen on form), then 4-digit group
    postal = cfg.get("postal_code", "").replace("-", "")
    draw_spaced(c, h["postal_x"],  h["postal_y"], h["postal_dx"], postal[:3])
    draw_spaced(c, h["postal_x2"], h["postal_y"], h["postal_dx"], postal[3:])

    # My number (12 digits)
    mn = cfg.get("my_number", "").replace(" ", "").replace("-", "")
    draw_spaced(c, h["mynum_x"], h["mynum_y"], h["mynum_dx"], mn)

    # Address — split at first digit/hyphen to fit two lines
    addr = cfg.get("address_1", "")
    split = next((i for i, ch in enumerate(addr) if ch.isdigit()), len(addr))
    c.setFont(FONT_NAME, 7)
    c.drawString(h["address_x"],  h["address_y"],  addr[:split])
    c.drawString(h["address2_x"], h["address2_y"], addr[split:])

    # Furigana + name
    c.drawString(h["furigana_x"], h["furigana_y"], cfg.get("furigana", ""))
    c.setFont(FONT_NAME, 8)
    c.drawString(h["name_x"], h["name_y"], cfg.get("name_katakana", ""))
    c.drawString(h["occupation_x"], h["occupation_y"], cfg.get("occupation", ""))

    # Phone
    c.drawString(h["phone1_x"], h["phone_y"], cfg.get("phone_1", ""))
    c.drawString(h["phone2_x"], h["phone_y"], cfg.get("phone_2", ""))
    c.drawString(h["phone3_x"], h["phone_y"], cfg.get("phone_3", ""))

    # DOB: era (1 digit) + year (2) + month (2) + day (2)
    dy, dx = h["dob_y"], h["dob_dx"]
    c.setFont(FONT_NAME, 8)
    c.drawString(h["dob_era_x"], dy, cfg.get("dob_era", ""))
    draw_spaced(c, h["dob_year_x"], dy, dx, str(cfg.get("dob_year",  "")).zfill(2))
    draw_spaced(c, h["dob_mon_x"],  dy, dx, str(cfg.get("dob_month", "")).zfill(2))
    draw_spaced(c, h["dob_day_x"],  dy, dx, str(cfg.get("dob_day",   "")).zfill(2))

    # Asset values
    for line, (px, py) in FA6003_POS.items():
        val = totals.get(line, 0)
        if val:
            c.drawString(px, py, fmt(val))

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    assets_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCRIPT_DIR / "assets.csv"
    config_path = Path(sys.argv[2]) if len(sys.argv) > 2 else SCRIPT_DIR / "config.csv"
    out_dir = SCRIPT_DIR / "output"
    out_dir.mkdir(exist_ok=True)

    print(f"config : {config_path}")
    cfg = read_config(config_path)
    fx  = extract_fx(cfg)
    print(f"FX     : {fx}  [{cfg.get('fx_source', '?')}]")

    print(f"assets : {assets_path}")
    assets = process_assets(read_assets(assets_path), fx)

    register_font()

    # ── FA6103 ──────────────────────────────────────────────────────────────────
    rows, overseas_total = build_fa6103_rows(assets)
    print(f"\nFA6103  ({len(rows)} rows)")
    for r in rows:
        print(f"  {r['kind']:<12}  {r['use']}  {r['location']:<22}  {r['quantity']:<6}  {fmt_jp(r['amount_jpy'])}")

    overlay = make_overlay(lambda c: draw_fa6103(c, cfg, rows, overseas_total))
    result  = apply_overlay(FA6103_BLANK, overlay)
    out     = out_dir / "FA6103-filled.pdf"
    out.write_bytes(result.read())
    print(f"\n✓  {out}")

    # ── FA6003 ──────────────────────────────────────────────────────────────────
    totals = build_fa6003_totals(assets, overseas_total)
    print(f"\nFA6003  totals")
    for line in sorted(totals, key=lambda x: int(x)):
        if totals[line]:
            print(f"  line {line:>2}  {fmt_jp(totals[line])}")

    overlay = make_overlay(lambda c: draw_fa6003(c, cfg, totals))
    result  = apply_overlay(FA6003_BLANK, overlay)
    out     = out_dir / "FA6003-filled.pdf"
    out.write_bytes(result.read())
    print(f"✓  {out}")


if __name__ == "__main__":
    main()
