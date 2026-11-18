//go:build android && amd64

// This file is copied only into a disposable x86_64 QA build, never a product build.
package main

import "os"

func init() {
	// Android app sandbox ownership confines each marker to its own QA package.
	for _, root := range []string{
		"/data/user/0/dev.herdr.herdr_flutter_probe/files/",
		"/data/user/0/dev.herdrpocket.tauriprobe/files/",
	} {
		marker, err := os.Stat(root + "enable-dual-overlay-private-ca")
		if err != nil || !marker.Mode().IsRegular() {
			continue
		}
		dir, err := os.Stat(root + "empty-dual-overlay-ca")
		if err != nil || !dir.IsDir() {
			continue
		}
		_ = os.Setenv("SSL_CERT_FILE", root+"dual-overlay-ca.pem")
		_ = os.Setenv("SSL_CERT_DIR", root+"empty-dual-overlay-ca")
		return
	}
}
