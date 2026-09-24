# The collections agent's tool server (ADR-022): the catalogue d-03 and f-01 put behind the gateway.
# python:3.12-slim publishes linux/amd64 and linux/arm64, which labs/README.md requires.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8852
CMD ["python", "server.py"]
