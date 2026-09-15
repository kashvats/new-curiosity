FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --create-home --uid 10001 deployer && mkdir -p /data && chown -R deployer:deployer /app /data
USER deployer
EXPOSE 8015
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8015"]
