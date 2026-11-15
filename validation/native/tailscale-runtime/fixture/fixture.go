// Package fixture is an opt-in, loopback-only control plane and real tsnet peer.
// It is test infrastructure, never a production trust or authentication path.
package fixture

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"tailscale.com/envknob"
	"tailscale.com/ipn/store/mem"
	"tailscale.com/logtail"
	"tailscale.com/net/netns"
	"tailscale.com/tailcfg"
	"tailscale.com/tsnet"
	"tailscale.com/tstest/integration"
	"tailscale.com/tstest/integration/testcontrol"
	"tailscale.com/types/logger"
)

const PeerPort = 2222

type Ready struct {
	Event      string `json:"event"`
	ControlURL string `json:"controlUrl"`
	CAFile     string `json:"caFile"`
	PeerIP     string `json:"peerIp"`
	PeerPort   int    `json:"peerPort"`
	DERPPort   int    `json:"derpPort"`
	STUNPort   int    `json:"stunPort"`
}

type Fixture struct {
	Ready
	control  *testcontrol.Server
	peer     *tsnet.Server
	listener net.Listener
	bridge   string
	mu       sync.Mutex
	closed   bool
	active   map[net.Conn]bool
	wg       sync.WaitGroup
	closeErr error
}

var trustOnce sync.Once

// New uses only temporary in-memory identities and the supplied owned work dir.
// An empty bridge means a local echo target for the product adapter regression.
func New(t testing.TB, work, bridge string) *Fixture {
	t.Helper()
	if !filepath.IsAbs(work) {
		t.Fatal("fixture requires an absolute owned work directory")
	}
	if err := os.MkdirAll(work, 0700); err != nil {
		t.Fatal("fixture work directory unavailable")
	}
	if files, err := os.ReadDir(work); err != nil || len(files) != 0 {
		t.Fatal("fixture requires an empty owned work directory")
	}
	if bridge != "" {
		host, _, err := net.SplitHostPort(bridge)
		ip, parseErr := netip.ParseAddr(host)
		if err != nil || parseErr != nil || !ip.IsLoopback() {
			t.Fatal("bridge must be an explicit loopback TCP address")
		}
		conn, err := net.DialTimeout("tcp", bridge, 3*time.Second)
		if err != nil {
			t.Fatal("loopback SSH bridge is not ready")
		}
		conn.Close() // Reachability only; no credentials or application bytes.
	}
	envknob.SetNoLogsNoSupport()
	logtail.Disable()
	netns.SetEnabled(false)
	t.Cleanup(func() { netns.SetEnabled(true) })

	cert, ca := certificate(t)
	caFile := filepath.Join(work, "control-ca.pem")
	if err := os.WriteFile(caFile, ca, 0600); err != nil {
		t.Fatal("cannot save test CA")
	}
	// Test process only. Also works on macOS without modifying Keychain trust.
	// The separate Linux product process uses SSL_CERT_FILE before Go initializes.
	trustOnce.Do(func() {
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(ca) {
			t.Fatal("invalid test CA")
		}
		t.Setenv("GODEBUG", os.Getenv("GODEBUG")+",x509usefallbackroots=1")
		x509.SetFallbackRoots(pool)
	})

	derp := integration.RunDERPAndSTUN(t, logger.Discard, "127.0.0.1")
	control := &testcontrol.Server{DERPMap: derp, RequireAuth: true,
		DNSConfig: &tailcfg.DNSConfig{Proxied: true}, MagicDNSDomain: "fixture.invalid", Logf: logger.Discard}
	control.HTTPTestServer = httptest.NewUnstartedServer(control)
	control.HTTPTestServer.TLS = &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS12}
	control.HTTPTestServer.StartTLS()
	t.Cleanup(control.HTTPTestServer.Close)
	probe := &http.Client{Timeout: 3 * time.Second}
	response, err := probe.Get(control.HTTPTestServer.URL + "/key?v=1")
	if err != nil {
		if e, ok := err.(*url.Error); ok {
			t.Fatalf("test CA did not validate the loopback HTTPS control plane: %v", e.Err)
		}
		t.Fatal("test CA did not validate the loopback HTTPS control plane")
	}
	response.Body.Close()
	probe.CloseIdleConnections()
	peer := &tsnet.Server{Dir: filepath.Join(work, "peer"), Hostname: "fixture-peer", Store: new(mem.Store),
		Ephemeral: true, ControlURL: control.HTTPTestServer.URL, ExplicitAuthOnly: true,
		Logf: logger.Discard, UserLogf: logger.Discard}
	f := &Fixture{control: control, peer: peer, bridge: bridge, active: map[net.Conn]bool{}}
	t.Cleanup(func() {
		if err := f.Close(); err != nil {
			t.Error("fixture peer cleanup failed")
		}
	})
	if err := peer.Start(); err != nil {
		t.Fatal("fixture peer start failed")
	}
	lc, err := peer.LocalClient()
	if err != nil {
		t.Fatal("fixture peer local client unavailable")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	if err := lc.StartLoginInteractive(ctx); err != nil {
		t.Fatal("fixture peer login failed")
	}
	var peerIP, approved, lastState string
	for ctx.Err() == nil {
		status, err := lc.StatusWithoutPeers(ctx)
		if err == nil {
			lastState = status.BackendState
			if status.AuthURL != "" && status.AuthURL != approved {
				if !f.CompleteAuth(status.AuthURL) {
					t.Fatal("fixture peer authorization rejected")
				}
				approved = status.AuthURL
			}
			if status.BackendState == "Running" && len(status.TailscaleIPs) != 0 {
				peerIP = status.TailscaleIPs[0].String()
				break
			}
		}
		select {
		case <-ctx.Done():
		case <-time.After(20 * time.Millisecond):
		}
	}
	if peerIP == "" {
		t.Fatalf("fixture peer did not become ready: state=%s, authorized=%t", lastState, approved != "")
	}
	f.listener, err = peer.Listen("tcp", ":2222")
	if err != nil {
		t.Fatal("fixture peer TCP listener unavailable")
	}
	node := derp.Regions[1].Nodes[0]
	f.Ready = Ready{Event: "ready", ControlURL: control.HTTPTestServer.URL, CAFile: caFile,
		PeerIP: peerIP, PeerPort: PeerPort, DERPPort: node.DERPPort, STUNPort: node.STUNPort}
	f.wg.Add(1)
	go f.accept()
	return f
}

// CompleteAuth never logs or returns the one-time URL. Only this control origin
// and an existing generated path can authorize a synthetic node in this process.
func (f *Fixture) CompleteAuth(raw string) bool {
	u, err := url.Parse(raw)
	base, _ := url.Parse(f.control.HTTPTestServer.URL)
	if err != nil || u.Scheme != "https" || u.Host != base.Host || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return false
	}
	return f.control.CompleteAuth(raw)
}

func (f *Fixture) keep(c net.Conn) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.closed {
		c.Close()
		return false
	}
	f.active[c] = true
	return true
}

func (f *Fixture) release(c net.Conn) {
	c.Close()
	f.mu.Lock()
	delete(f.active, c)
	f.mu.Unlock()
}

func (f *Fixture) accept() {
	defer f.wg.Done()
	for {
		c, err := f.listener.Accept()
		if err != nil {
			return
		}
		if !f.keep(c) {
			return
		}
		f.wg.Add(1)
		go func() {
			defer f.wg.Done()
			defer f.release(c)
			if f.bridge == "" {
				io.Copy(c, c)
				return
			}
			local, err := net.DialTimeout("tcp", f.bridge, 3*time.Second)
			if err != nil || !f.keep(local) {
				return
			}
			defer f.release(local)
			done := make(chan struct{})
			go func() { io.Copy(local, c); local.Close(); close(done) }()
			io.Copy(c, local)
			c.Close()
			local.Close()
			<-done
		}()
	}
}

func (f *Fixture) Close() error {
	f.mu.Lock()
	if f.closed {
		err := f.closeErr
		f.mu.Unlock()
		return err
	}
	f.closed = true
	if f.listener != nil {
		f.listener.Close()
	}
	for c := range f.active {
		c.Close()
	}
	f.mu.Unlock()
	err := f.peer.Close()
	f.wg.Wait()
	f.mu.Lock()
	f.closeErr = err
	f.mu.Unlock()
	return err
}

func (f *Fixture) Connections() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.active)
}

func certificate(t testing.TB) (tls.Certificate, []byte) {
	t.Helper()
	rootKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal("test CA key generation failed")
	}
	now := time.Now()
	root := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "herdr disposable test CA"},
		NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), IsCA: true, BasicConstraintsValid: true,
		KeyUsage: x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature}
	rootDER, err := x509.CreateCertificate(rand.Reader, root, root, &rootKey.PublicKey, rootKey)
	if err != nil {
		t.Fatal("test CA certificate generation failed")
	}
	leafKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal("test TLS key generation failed")
	}
	leaf := &x509.Certificate{SerialNumber: big.NewInt(2), Subject: pkix.Name{CommonName: "localhost"},
		NotBefore: now.Add(-time.Minute), NotAfter: now.Add(time.Hour), DNSNames: []string{"localhost"},
		IPAddresses: []net.IP{net.ParseIP("127.0.0.1"), net.ParseIP("::1")},
		KeyUsage:    x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	leafDER, err := x509.CreateCertificate(rand.Reader, leaf, root, &leafKey.PublicKey, rootKey)
	if err != nil {
		t.Fatal("test TLS certificate generation failed")
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(leafKey)
	if err != nil {
		t.Fatal("test TLS key serialization failed")
	}
	ca := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: rootDER})
	cert, err := tls.X509KeyPair(append(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: leafDER}), ca...),
		pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}))
	if err != nil {
		t.Fatal("test TLS identity unavailable")
	}
	return cert, ca
}
