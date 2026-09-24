# Generates the lab's TLS certificate into a shared volume. Runs once and exits.
FROM alpine:3.22
RUN apk add --no-cache openssl
COPY generate.sh /usr/local/bin/generate
RUN chmod +x /usr/local/bin/generate
ENTRYPOINT ["/usr/local/bin/generate"]
