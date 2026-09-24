# The aquaflux-alt seeding proxy. See app.py for why this exists as a service.
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 11434
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "11434", "--no-access-log"]
