#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/network-vault-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
javac -d "$tmp" "$here/NetworkSecretStoreCore.java" "$here/tests/NetworkSecretStoreCoreTest.java"
java -cp "$tmp" org.herdr.network.NetworkSecretStoreCoreTest
