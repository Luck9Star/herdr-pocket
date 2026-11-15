package fixture

import (
	"bufio"
	"encoding/json"
	"os"
	"testing"
)

// This test is a process fixture, opt-in only. Normal candidate checks skip it.
func TestServeFixture(t *testing.T) {
	work := os.Getenv("HP_TS_FIXTURE_WORK_DIR")
	if work == "" {
		t.Skip("explicit fixture work directory required")
	}
	out := json.NewEncoder(os.Stdout)
	var f *Fixture
	// Registered before New: runs after its peer/control/DERP/STUN cleanups.
	t.Cleanup(func() {
		if f != nil {
			out.Encode(map[string]any{"event": "cleanup", "peerClosed": true, "bridgeConnections": f.Connections()})
		}
	})
	f = New(t, work, os.Getenv("HP_TS_FIXTURE_BRIDGE"))
	if err := out.Encode(f.Ready); err != nil {
		t.Fatal("fixture event output unavailable")
	}
	scan := bufio.NewScanner(os.Stdin)
	scan.Buffer(make([]byte, 4096), 8192)
	for scan.Scan() {
		var cmd struct {
			Op  string `json:"op"`
			URL string `json:"url"`
		}
		if json.Unmarshal(scan.Bytes(), &cmd) != nil {
			t.Fatal("invalid fixture command")
		}
		switch cmd.Op {
		case "diagnostics":
			out.Encode(f.Diagnostics())
		case "complete_auth":
			out.Encode(map[string]any{"event": "auth_completed", "ok": f.CompleteAuth(cmd.URL)})
		case "stop":
			if err := f.Close(); err != nil {
				t.Fatal("fixture peer close failed")
			}
			return
		default:
			t.Fatal("unknown fixture command")
		}
	}
	if scan.Err() != nil {
		t.Fatal("fixture command input failed")
	}
	if err := f.Close(); err != nil {
		t.Fatal("fixture EOF cleanup failed")
	}
}
