# The identity provider. Keycloak, with the Aquaflux realm baked in rather than bind-mounted:
# nothing but the workspace mounts a host path, because the Compose client is now a terminal
# inside the dev container. docker-compose.yml explains that once.
#
# The TLS certificate is not made here. This image has no openssl, and the `tls` service
# generates it into a shared volume before this one starts.
FROM quay.io/keycloak/keycloak:26.7.4

COPY --chown=keycloak:root aquaflux-realm.json /opt/keycloak/data/import/aquaflux-realm.json

EXPOSE 443
