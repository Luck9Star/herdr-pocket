#!/system/bin/sh
# Test package only: roots are read from this process's private files before Go loads.
export SSL_CERT_FILE=/data/user/0/org.herdr.tlsprobe/files/ca.pem
export SSL_CERT_DIR=/data/user/0/org.herdr.tlsprobe/files/empty-ca
exec "$@"
