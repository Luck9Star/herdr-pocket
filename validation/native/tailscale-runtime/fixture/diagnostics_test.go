package fixture

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDiagnosticsExcludePeerStartupAndSensitiveText(t *testing.T) {
	c := new(counters)
	c.top("/key")
	c.machine(httptest.NewRequest("POST", "/machine/register", nil))
	c.Write([]byte("TLS handshake error from synthetic-private-value"))
	if c.key.Load()+c.register.Load()+c.tlsError.Load() != 0 {
		t.Fatal("startup leaked into post-ready counts")
	}
	c.enabled.Store(true)
	c.top("/key")
	c.top("/ts2021")
	status, retry, message := c.machine(httptest.NewRequest("POST", "/machine/register", nil))
	c.machine(httptest.NewRequest("POST", "/machine/map", nil))
	c.Write([]byte("TLS handshake error from synthetic-private-value"))
	if status != 0 || retry != "" || message != "" {
		t.Fatal("diagnostic hook changed behavior")
	}
	if c.key.Load() != 1 || c.noise.Load() != 1 || c.register.Load() != 1 || c.mapPoll.Load() != 1 || c.tlsError.Load() != 1 {
		t.Fatal("diagnostic classification failed")
	}
	b, _ := json.Marshal(Diagnostics{Event: "diagnostics", KeyRequests: c.key.Load(), TLSHandshakeErrors: c.tlsError.Load()})
	if strings.Contains(string(b), "synthetic-private-value") {
		t.Fatal("diagnostics retained request text")
	}
}
