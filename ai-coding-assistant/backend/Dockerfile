FROM python:3.11-slim-bullseye

WORKDIR /app

COPY requirements.txt requirements-operations.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-operations.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
