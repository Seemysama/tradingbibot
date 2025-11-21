PY=python3.11
VENV?=.venv
ACT=source $(VENV)/bin/activate

.PHONY: venv install api ui lint type test

venv:
	$(PY) -m venv $(VENV)
	$(ACT) && pip install --upgrade pip

install: venv
	$(ACT) && pip install -r requirements.txt

api:
	$(ACT) && uvicorn api.server:app --reload

ui:
	$(ACT) && streamlit run ui/app.py

lint:
	$(ACT) && ruff check .

type:
	$(ACT) && mypy --strict .

test:
	$(ACT) && pytest -q
