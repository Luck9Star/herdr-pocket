package fixture

import (
	"bytes"
	"net/http"
	"sync/atomic"
)

// Counters start only after the fixture's own peer is ready. They contain no
// request bodies, identities, addresses, URLs or TLS error text.
type counters struct {
	enabled    atomic.Bool
	key        atomic.Uint64
	noise      atomic.Uint64
	register   atomic.Uint64
	mapPoll    atomic.Uint64
	tlsError   atomic.Uint64
	authorized atomic.Uint64
}

func (c *counters) top(path string) {
	if !c.enabled.Load() {
		return
	}
	switch path {
	case "/key":
		c.key.Add(1)
	case "/ts2021":
		c.noise.Add(1)
	}
}

func (c *counters) machine(r *http.Request) (int, string, string) {
	if c.enabled.Load() {
		switch r.URL.Path {
		case "/machine/register":
			c.register.Add(1)
		case "/machine/map":
			c.mapPoll.Add(1)
		}
	}
	return 0, "", "" // Observe only: never reject, approve or modify a request.
}

func (c *counters) Write(p []byte) (int, error) {
	if c.enabled.Load() && bytes.Contains(p, []byte("TLS handshake error")) {
		c.tlsError.Add(1)
	}
	return len(p), nil
}

type Diagnostics struct {
	Event                  string `json:"event"`
	KeyRequests            uint64 `json:"keyRequests"`
	NoiseRequests          uint64 `json:"noiseRequests"`
	RegisterRequests       uint64 `json:"registerRequests"`
	MapRequests            uint64 `json:"mapRequests"`
	TLSHandshakeErrors     uint64 `json:"tlsHandshakeErrors"`
	SecondClientRegistered bool   `json:"secondClientRegistered"`
	AuthCompletions        uint64 `json:"authCompletions"`
}

func (f *Fixture) Diagnostics() Diagnostics {
	c := f.counters
	return Diagnostics{Event: "diagnostics", KeyRequests: c.key.Load(), NoiseRequests: c.noise.Load(),
		RegisterRequests: c.register.Load(), MapRequests: c.mapPoll.Load(), TLSHandshakeErrors: c.tlsError.Load(),
		SecondClientRegistered: f.control.NumNodes() > f.baselineNodes, AuthCompletions: c.authorized.Load()}
}
