// Test-only Android JNI bridge: standard Go TLS, no custom trust or TLS bypass.
package main

/*
#include <jni.h>
*/
import "C"

import (
	"context"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"time"
)

//export Java_org_herdr_tlsprobe_ProbeInstrumentation_probe
func Java_org_herdr_tlsprobe_ProbeInstrumentation_probe(env *C.JNIEnv, clazz C.jclass, port C.jint, wrongHost C.jboolean) C.jint {
	const root = "/data/user/0/org.herdr.tlsprobe/files/"
	if os.Getenv("SSL_CERT_FILE") != root+"ca.pem" || os.Getenv("SSL_CERT_DIR") != root+"empty-ca" {
		return 8
	}
	address := fmt.Sprintf("127.0.0.1:%d", int(port))
	hostname := "127.0.0.1"
	if wrongHost != 0 {
		hostname = "wrong.invalid"
	}
	transport := &http.Transport{Proxy: nil, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "tcp", address)
	}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 8 * time.Second}
	response, err := client.Get("https://" + hostname + ":" + fmt.Sprint(int(port)) + "/key")
	if err != nil {
		var unknown x509.UnknownAuthorityError
		if errors.As(err, &unknown) {
			return 1
		}
		var mismatch x509.HostnameError
		if errors.As(err, &mismatch) {
			return 2
		}
		return 9
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 128))
	if err != nil || response.StatusCode != 200 || string(body) != "HP-GO-TLS-OK" {
		return 10
	}
	return 0
}

func main() {}
