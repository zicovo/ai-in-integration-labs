# Seeds d-04's history into the trace store and the gateway's decision file. Standard library
# only. python:3.12-slim publishes linux/amd64 and linux/arm64, which labs/README.md requires.
FROM python:3.12-slim
WORKDIR /srv
COPY app.py .
CMD ["python", "-u", "app.py"]
