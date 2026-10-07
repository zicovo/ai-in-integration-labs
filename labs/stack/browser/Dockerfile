# A browser inside the lab network.
#
# The one part of the stack a learner touches that is not in the Compose network is their own
# browser, which is why the addresses in a terminal and the addresses in a browser were two
# different things. This puts a browser on the network, so `https://idp.aquaflux.internal` is the
# address everywhere and there is one rule to teach instead of two.
#
# It is on the `ui` profile and starts only when asked for, because it costs about a gigabyte of
# memory and most labs never need it. Forwarded localhost ports keep working for anyone who would
# rather use their own browser.
#
# jlesage/firefox publishes linux/amd64 and linux/arm64, which labs/README.md requires of every
# image here.
# Pinned by version and digest, like every other image in the stack (labs/stack/images.yml).
FROM jlesage/firefox:v26.08.3@sha256:193ef860a97b161f5f92dde0476550673e9905a6eaf12f376fd1f059068ab45b

# Firefox keeps its own certificate store and does not read the system one, so the lab's
# certificate is installed through an enterprise policy instead. Without this the identity
# provider greets every participant with a warning to click past, which is precisely the habit
# carry-the-authority exists to argue against.
COPY policies.json /usr/lib/firefox/distribution/policies.json
# The toolbar is rebuilt from the policy at every start; the script says why.
COPY --chmod=0755 57-aquaflux-bookmarks.sh /etc/cont-init.d/57-aquaflux-bookmarks.sh

# The startup tabs and the bookmarks toolbar are set by the policy, not here, so that there is
# one place to add a service to when a profile is built.
ENV APP_NAME="Aquaflux lab browser" \
    DARK_MODE=1 \
    KEEP_APP_RUNNING=1
