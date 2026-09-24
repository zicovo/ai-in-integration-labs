# The model gateway, with its configuration built in rather than bind-mounted.
#
# No service in this stack except `workspace` bind-mounts a host path. A bind is resolved by the
# Compose client, and the client here is a terminal inside the dev container, so the path would
# reach the host daemon meaning something that exists only in the container. A build context is
# streamed to the daemon and does not have that problem. docker-compose.yml explains it once.
FROM ghcr.io/berriai/litellm:v1.83.14-stable

USER root
# The settings, and one model list per provider. entrypoint.sh picks a list at startup and
# concatenates it with the settings; dec:OD-025 explains why there are two.
COPY config.yaml /etc/litellm/config.yaml
COPY models.azure.yaml /etc/litellm/models.azure.yaml
COPY models.hosted.yaml /etc/litellm/models.hosted.yaml
COPY models.local.yaml /etc/litellm/models.local.yaml
COPY embed.hosted.yaml embed.azure.yaml embed.local.yaml /etc/litellm/
COPY entrypoint.sh /usr/local/bin/aquaflux-entrypoint
RUN chmod +x /usr/local/bin/aquaflux-entrypoint

EXPOSE 4000
ENTRYPOINT ["/usr/local/bin/aquaflux-entrypoint"]
