# Terminates TLS for every Aquaflux address. See Caddyfile for why this is one service and not
# a setting on each of the others.
FROM caddy:2.10-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY start.html /srv/start/index.html
