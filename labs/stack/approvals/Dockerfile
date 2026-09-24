# The approval service (ADR-022). Written for the labs, like the three Aquaflux stand-ins.
# python:3.12-slim publishes linux/amd64 and linux/arm64, which labs/README.md requires.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 80
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80", "--no-access-log"]
