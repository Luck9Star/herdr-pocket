package tsdial

import (
	"context"
	"errors"
	"net/netip"
	"testing"
)

func TestHerdrDialPlanUsesOnlyThisNodesNamesAndRoutes(t *testing.T) {
	peer := netip.MustParseAddr("100.64.0.2")
	subnet := netip.MustParsePrefix("192.0.2.0/24")
	d := &Dialer{UseNetstackForIP: func(ip netip.Addr) bool { return ip == peer || subnet.Contains(ip) }}
	lookups := 0
	d.SetResolveMagicDNS(func(hostname, network string) (netip.Addr, bool) {
		lookups++
		if network == "tcp" && (hostname == "peer" || hostname == "peer.example.ts.net" || hostname == "service.example") {
			return peer, true
		}
		return netip.Addr{}, false
	})
	for _, address := range []string{"100.64.0.2:22", "[::ffff:100.64.0.2]:22", "peer:22", "PEER.EXAMPLE.TS.NET.:22", "service.example:22", "192.0.2.17:22"} {
		before := lookups
		ipp, routed, err := d.UserDialPlanWithoutDNSFallback(context.Background(), "tcp", address)
		if err != nil || !routed || !ipp.IsValid() || lookups-before > 1 {
			t.Fatal("legitimate node-local address was rejected or resolved twice")
		}
	}
	if _, _, err := d.UserDialPlanWithoutDNSFallback(context.Background(), "tcp", "unknown.invalid:22"); !errors.Is(err, errUnresolved) {
		t.Fatal("unknown name must fail at local map, not reach an OS resolver")
	}
	for _, address := range []string{"127.0.0.1:22", "198.51.100.17:22", "[::1]:22"} {
		if _, routed, err := d.UserDialPlanWithoutDNSFallback(context.Background(), "tcp", address); err != nil || routed {
			t.Fatal("unapproved route was not rejected")
		}
	}
	// Preserve the official route-table path as well as UseNetstackForIP.
	d.UseNetstackForIP = nil
	d.SetRoutes([]netip.Prefix{subnet}, nil)
	if _, routed, err := d.UserDialPlanWithoutDNSFallback(context.Background(), "tcp", "192.0.2.17:22"); err != nil || !routed {
		t.Fatal("approved subnet route was lost")
	}
}
