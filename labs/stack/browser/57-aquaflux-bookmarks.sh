#!/bin/sh
# Start the lab browser's bookmarks from policies.json, every time.
#
# The profile is a named volume, and Firefox's Bookmarks policy only ever adds: a shortcut that
# moved (the systems of record used to open on /docs) stays beside its replacement under the same
# title. Deleting places.sqlite alone is not enough either, because Firefox restores a missing
# database from bookmarkbackups/. So both go, before Firefox starts, and the policy is the only
# source of the toolbar. The lab browser's history goes with them, which a lab never needs.
set -eu
rm -f /config/profile/places.sqlite /config/profile/places.sqlite-wal /config/profile/places.sqlite-shm \
      /config/profile/favicons.sqlite /config/profile/favicons.sqlite-wal /config/profile/favicons.sqlite-shm
rm -rf /config/profile/bookmarkbackups
