.PHONY: install run check

install:
	pip3 install -r requirements.txt

run:
	python3 fill_forms.py

check:
	@python3 -c "import reportlab, pypdf; print('packages ok')"
	@python3 -c "import fill_forms; print('font:', fill_forms.FONT_PATH)"
