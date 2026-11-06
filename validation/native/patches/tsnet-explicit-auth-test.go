// Downstream isolated contract tests. No tsnet Server is started.
package tsnet

import (
	"testing"

	"tailscale.com/ipn"
)

func TestHerdrExplicitAuthRejectsAmbientInputs(t *testing.T) {
	for _, name := range []string{"TS_AUTHKEY", "TS_AUTH_KEY", "TS_CLIENT_SECRET", "TS_CLIENT_ID", "TS_ID_TOKEN", "TS_AUDIENCE", "TS_CONTROL_URL", "TSNET_FORCE_LOGIN"} {
		t.Setenv(name, "synthetic-fixture-only")
	}
	s := &Server{ExplicitAuthOnly: true}
	for name, value := range map[string]string{"auth": s.getAuthKey(), "control": s.getControlURL(), "secret": s.getClientSecret(), "client": s.getClientID(), "token": s.getIDToken(), "audience": s.getAudience()} {
		if value != "" {
			t.Fatalf("ambient %s was accepted", name)
		}
	}
	if key, err := s.resolveAuthKey(); err != nil || key != "" {
		t.Fatal("explicit empty authentication invoked a resolver")
	}
	if s.shouldStartInteractive(ipn.NeedsLogin) || s.shouldStartInteractive(ipn.Running) {
		t.Fatal("implicit or forced interactive login admitted")
	}
}

func TestHerdrExplicitAuthKeepsExplicitFields(t *testing.T) {
	t.Setenv("TS_AUTHKEY", "synthetic-ambient")
	s := &Server{ExplicitAuthOnly: true, AuthKey: "synthetic-explicit", ControlURL: "https://control.example.invalid"}
	if s.getAuthKey() != "synthetic-explicit" || s.getControlURL() != s.ControlURL {
		t.Fatal("explicit configuration lost")
	}
	if key, err := s.resolveAuthKey(); err != nil || key != "synthetic-explicit" {
		t.Fatal("explicit key was routed through an external resolver")
	}
}

func TestHerdrPatchLeavesDefaultGetterCompatibility(t *testing.T) {
	t.Setenv("TS_AUTHKEY", "synthetic-legacy")
	t.Setenv("TS_CONTROL_URL", "https://legacy.example.invalid")
	s := &Server{}
	if s.getAuthKey() != "synthetic-legacy" || s.getControlURL() != "https://legacy.example.invalid" {
		t.Fatal("non-opt-in upstream getters changed")
	}
}
