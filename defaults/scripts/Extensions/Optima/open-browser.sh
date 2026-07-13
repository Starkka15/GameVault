#!/bin/bash
# Wrapper to open URLs in Firefox Flatpak for the Ubisoft WebAuth login.
# optima-cli calls $BROWSER <url> (via the `open` crate); flatpak needs its own
# argv, so we can't just point $BROWSER straight at the flatpak id.
exec flatpak run org.mozilla.firefox "$@"
