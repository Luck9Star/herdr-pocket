package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"time"

	"herdr.local/tailscale-runtime/fixture"
	"tailscale.com/tstest"
)

// Explicit opt-in preserves the normal candidate tool's never-start guarantee.
func TestRealHTTPSExplicitLoginAndTCP(t *testing.T) {
	if os.Getenv("HP_TS_REAL_LOOPBACK") != "1" {
		t.Skip("explicit real loopback opt-in required")
	}
	tstest.ResourceCheck(t)
	f := fixture.New(t, t.TempDir(), "")
	m := newManager(makeTSEngine)
	id, result := m.newNode(config{Directory: filepath.Join(t.TempDir(), "product"),
		Hostname: "product-fixture", ControlURL: f.ControlURL}, &memoryStore{values: map[string][]byte{}})
	if result != ok {
		t.Fatal("product node creation failed")
	}
	t.Cleanup(func() { m.nodeClose(id, 10000) })
	if m.start(id, 10000) != ok {
		t.Fatal("product node start failed")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	await := func(condition func() bool) {
		t.Helper()
		for !condition() {
			select {
			case <-ctx.Done():
				t.Fatal("product fixture phase timed out")
			case <-time.After(20 * time.Millisecond):
			}
		}
	}
	await(func() bool {
		s, c := m.control(id, 5000, false)
		return c == ok && s.State == "NeedsLogin"
	})
	raw, err := m.getNode(id).engine.Status(ctx)
	if err != nil || raw.AuthURL != "" {
		t.Fatal("pre-login product engine exposed an authorization URL")
	}
	address := fmt.Sprintf("%s:%d", f.PeerIP, f.PeerPort)
	if stream, c := m.dial(id, address, 1000); c != notRunning || stream != 0 {
		t.Fatal("pre-login product node accepted TCP dial")
	}
	if _, c := m.control(id, 5000, true); c != ok {
		t.Fatal("explicit product login failed")
	}
	var authURL string
	await(func() bool {
		s, c := m.control(id, 5000, false)
		if c == ok && s.AuthURL != "" {
			authURL = s.AuthURL
			return true
		}
		return false
	})
	u, err := url.Parse(authURL)
	base, _ := url.Parse(f.ControlURL)
	if err != nil || u.Scheme != "https" || u.Host != base.Host || u.User != nil || u.Fragment != "" {
		t.Fatal("product did not return a valid fixture HTTPS authorization URL")
	}
	if !f.CompleteAuth(authURL) {
		t.Fatal("explicit fixture authorization failed")
	}
	authURL = "" // One-time URL never enters logs or result JSON.
	await(func() bool {
		s, c := m.control(id, 5000, false)
		return c == ok && s.State == "Running"
	})
	diagnostics := f.Diagnostics()
	if diagnostics.KeyRequests == 0 || diagnostics.NoiseRequests == 0 || diagnostics.RegisterRequests == 0 ||
		!diagnostics.SecondClientRegistered || diagnostics.AuthCompletions != 1 || diagnostics.TLSHandshakeErrors != 0 {
		t.Fatal("fixture diagnostics did not distinguish the product client")
	}
	stream, c := m.dial(id, address, 10000)
	if c != ok {
		t.Fatal("product userspace TCP dial failed")
	}
	payload := []byte("synthetic userspace TCP: 中文 😀\n")
	_, count, c := m.streamIO(stream, payload, len(payload), 5000, true, false)
	if c != ok || count != len(payload) {
		t.Fatal("product TCP write incomplete")
	}
	var got []byte
	for len(got) < len(payload) {
		chunk, _, c := m.streamIO(stream, nil, len(payload)-len(got), 5000, false, false)
		if c != ok || len(chunk) == 0 {
			t.Fatal("product TCP read incomplete")
		}
		got = append(got, chunk...)
	}
	if !bytes.Equal(got, payload) {
		t.Fatal("product TCP payload mismatch")
	}
	if m.streamClose(stream, 10000) != ok || m.streamRelease(stream) != ok || m.nodeClose(id, 10000) != ok || m.nodeRelease(id) != ok {
		t.Fatal("product handle cleanup failed")
	}
	m.mu.Lock()
	nodes, streams := len(m.nodes), len(m.streams)
	m.mu.Unlock()
	if nodes != 0 || streams != 0 {
		t.Fatal("product handles retained after release")
	}
	if f.Close() != nil || f.Connections() != 0 {
		t.Fatal("fixture streams retained after close")
	}
	report, _ := json.Marshal(map[string]any{"event": "product_loopback", "preLoginNoAuthUrl": true,
		"preLoginDialRejected": true, "explicitHttpsAuth": true, "running": true,
		"tcpPayloadEqual": true, "bytes": len(payload), "nodes": nodes, "streams": streams,
		"bridgeConnections": f.Connections()})
	t.Log(string(report))
}
