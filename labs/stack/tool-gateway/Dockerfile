# The tool gateway the labs run against (ADR-021).
#
# python:3.12-slim publishes linux/amd64 and linux/arm64, which labs/README.md requires of every
# image in the stack.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY policies ./policies
COPY app ./app

EXPOSE 4444
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4444", "--no-access-log"]
