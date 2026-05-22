import sys
import zipfile
import tempfile
from pathlib import Path
from io import BytesIO

# allow importing fill_forms from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

import fill_forms as ff
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse

app = FastAPI()

_INDEX = Path(__file__).parent / "static" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def index():
    return _INDEX.read_text()


@app.post("/generate")
async def generate(
    assets_csv: UploadFile = File(...),
    config_csv: UploadFile = File(...),
):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        assets_path = tmp / "assets.csv"
        config_path = tmp / "config.csv"
        assets_path.write_bytes(await assets_csv.read())
        config_path.write_bytes(await config_csv.read())

        out_dir = tmp / "output"
        out_dir.mkdir()

        try:
            cfg = ff.read_config(config_path)
            cfg.pop("my_number", None)  # never write My Number into output PDFs

            fx = ff.extract_fx(cfg)
            assets = ff.process_assets(ff.read_assets(assets_path), fx)
            ff.register_font()

            rows, overseas_total = ff.build_fa6103_rows(assets)
            overlay = ff.make_overlay(lambda c: ff.draw_fa6103(c, cfg, rows, overseas_total))
            (out_dir / "FA6103-filled.pdf").write_bytes(ff.apply_overlay(ff.FA6103_BLANK, overlay).read())

            totals = ff.build_fa6003_totals(assets, overseas_total)
            overlay = ff.make_overlay(lambda c: ff.draw_fa6003(c, cfg, totals))
            (out_dir / "FA6003-filled.pdf").write_bytes(ff.apply_overlay(ff.FA6003_BLANK, overlay).read())

            oar_rows = ff.build_fa5003_rows(assets)
            overlay = ff.make_overlay(lambda c: ff.draw_fa5003_detail(c, cfg, oar_rows))
            (out_dir / "FA5003-detail-filled.pdf").write_bytes(ff.apply_overlay(ff.FA5003D_BLANK, overlay).read())

            oar_totals = ff.build_fa5003_totals(assets)
            overlay = ff.make_overlay(lambda c: ff.draw_fa5003_summary(c, cfg, oar_totals))
            (out_dir / "FA5003-summary-filled.pdf").write_bytes(ff.apply_overlay(ff.FA5003S_BLANK, overlay).read())

        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for pdf in sorted(out_dir.glob("*.pdf")):
                zf.write(pdf, pdf.name)
        zip_buf.seek(0)

        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=tax-forms.zip"},
        )
