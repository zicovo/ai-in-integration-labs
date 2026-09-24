#!/bin/sh
# Generate the lab's certificate authority and one server certificate, into a volume every
# container that needs them can mount.
#
# Why TLS at all, and everywhere: a participant who meets "Not Secure" on every internal service,
# and learns to click past a certificate warning to get on with the exercise, has been taught
# something this course spends two modules arguing against. The stack is the example, so the
# stack is served properly.
#
# Why generated and not committed: a private key in a git repository is a bad habit in any
# project and a worse one in a course about securing agent traffic, even for a domain that does
# not exist.
#
# THE MISTAKE THIS FILE EXISTS TO NOT REPEAT. The first version generated one self-signed
# certificate with basicConstraints CA:TRUE and served it directly. Every command line client
# accepted it, so it looked finished. Browsers do not: a certificate authority certificate
# presented as a server certificate is refused by Firefox and Chrome with
# CA_CERT_USED_AS_END_ENTITY, and no amount of installing it in a trust store helps, because the
# objection is to what the certificate claims to be and not to who signed it. The only fix is a
# real chain: a root that signs, and a leaf that serves and signs nothing.

set -eu

TLS_DIR=/etc/aquaflux/tls
CA_CRT="$TLS_DIR/ca.crt"
CA_KEY="$TLS_DIR/ca.key"
CRT="$TLS_DIR/server.crt"
KEY="$TLS_DIR/server.key"

mkdir -p "$TLS_DIR"
rm -f "$TLS_DIR/idp.crt" "$TLS_DIR/idp.key"   # from the version this file warns about

if [ -s "$CA_CRT" ] && [ -s "$CRT" ] && [ -s "$KEY" ]; then
  echo "tls: certificates already present, leaving them alone"
  exit 0
fi

echo "tls: generating the Aquaflux lab certificate authority"
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout "$CA_KEY" -out "$CA_CRT" \
  -subj "/C=BE/O=Aquaflux fictional utility/OU=AI in Integration labs/CN=Aquaflux lab root CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

echo "tls: generating the server certificate for *.aquaflux.internal"
openssl req -newkey rsa:2048 -nodes \
  -keyout "$KEY" -out "$TLS_DIR/server.csr" \
  -subj "/C=BE/O=Aquaflux fictional utility/OU=AI in Integration labs/CN=*.aquaflux.internal"

# One wildcard covers every service, because a single label wildcard matches
# idp.aquaflux.internal, wom.aquaflux.internal and the rest. CA:FALSE is the whole point: this
# certificate serves and signs nothing.
cat > "$TLS_DIR/server.ext" <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:*.aquaflux.internal,DNS:aquaflux.internal,DNS:localhost,IP:127.0.0.1
EXT

openssl x509 -req -in "$TLS_DIR/server.csr" -sha256 -days 3650 \
  -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -out "$CRT" -extfile "$TLS_DIR/server.ext"

rm -f "$TLS_DIR/server.csr" "$TLS_DIR/server.ext" "$TLS_DIR/.srl" "$TLS_DIR"/*.srl

chmod 0644 "$CA_CRT" "$CRT"
chmod 0644 "$KEY"

echo "tls: verifying the chain before anything tries to serve it"
openssl verify -CAfile "$CA_CRT" "$CRT"
openssl x509 -in "$CRT" -noout -ext basicConstraints | tail -1 | grep -q "CA:FALSE" \
  || { echo "tls: the server certificate claims to be a CA, which browsers refuse" >&2; exit 1; }

echo "tls: done"
