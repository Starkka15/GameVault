#!/bin/bash
# Wrapper to open URLs in Firefox Flatpak for EA OAuth login.
# maxima-cli calls $BROWSER <url>, but flatpak needs multiple args.
exec flatpak run org.mozilla.firefox "$@"
