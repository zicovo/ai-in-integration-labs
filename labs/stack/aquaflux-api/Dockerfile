# The three Aquaflux stand-in APIs. One image, three containers; AQUAFLUX_SYSTEM picks which.
# python:3.12-slim publishes linux/amd64 and linux/arm64, which labs/README.md requires of every
# image in the stack: an amd64-only image runs under emulation on an M-series Mac and ruins a
# session.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Swagger's assets are vendored rather than pulled from a CDN at page load. FastAPI's default
# /docs references cdn.jsdelivr.net, so in a room with no internet, or behind a corporate proxy
# that blocks it, the API documentation renders as a blank page. dec:OD-010 says these labs run
# on a laptop; a page that needs the internet to explain an API is not local-first.
ARG SWAGGER_VERSION=5.17.14
ADD https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWAGGER_VERSION}/swagger-ui-bundle.js /srv/static/swagger-ui-bundle.js
ADD https://cdn.jsdelivr.net/npm/swagger-ui-dist@${SWAGGER_VERSION}/swagger-ui.css /srv/static/swagger-ui.css
RUN chmod 0644 /srv/static/*

COPY app ./app

# Port 80, so the handouts can address these as http://wom.aquaflux.internal/v4 with no port. The
# platform components carry their port; the systems of record do not. That distinction is in
# labs/README.md and it is deliberate.
EXPOSE 80
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80", "--no-access-log"]
