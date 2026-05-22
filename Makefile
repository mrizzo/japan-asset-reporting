.PHONY: install run check serve

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt -r web/requirements.txt

run:
	python3 fill_forms.py

check:
	@python3 -c "import reportlab, pypdf; print('packages ok')"
	@python3 -c "import fill_forms; print('font:', fill_forms.FONT_PATH)"

serve:
	.venv/bin/uvicorn web.app:app --reload
