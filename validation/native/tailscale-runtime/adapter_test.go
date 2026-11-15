package main

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"testing"

	"tailscale.com/net/tsdial"
	"tailscale.com/tsnet"
)

func TestNetstackOnlyDialResolvesOnceAndPreservesNodeRoutes(t *testing.T) {
	peer := netip.MustParseAddr("100.64.0.2")
	peer6 := netip.MustParseAddr("fd7a:115c:a1e0::2")
	subnet := netip.MustParsePrefix("192.0.2.0/24")
	for _, tc := range []struct {
		address string
		allowed bool
	}{
		{"100.64.0.2:22", true}, {"[::ffff:100.64.0.2]:22", true},
		{"[fd7a:115c:a1e0::2]:22", true}, {"peer:22", true},
		{"PEER.EXAMPLE.TS.NET.:22", true}, {"service.example:22", true},
		{"192.0.2.17:22", true}, {"198.51.100.17:22", false},
		{"127.0.0.1:22", false}, {"[::1]:22", false},
		{"unknown.invalid:22", false}, {"localhost:22", false}, {"127.1:22", false},
	} {
		t.Run(tc.address, func(t *testing.T) {
			calls, systemCalls, resolutions := 0, 0, 0
			d := &tsdial.Dialer{UseNetstackForIP: func(ip netip.Addr) bool {
				return ip == peer || ip == peer6 || subnet.Contains(ip)
			}}
			d.SetResolveMagicDNS(func(name, network string) (netip.Addr, bool) {
				resolutions++
				if name == "peer" || name == "peer.example.ts.net" || name == "service.example" {
					return peer, true
				}
				return netip.Addr{}, false
			})
			d.SetSystemDialerForTest(func(context.Context, string, string) (net.Conn, error) {
				systemCalls++
				return nil, errors.New("forbidden system dial")
			})
			var other net.Conn
			d.NetstackDialTCP = func(_ context.Context, destination netip.AddrPort) (net.Conn, error) {
				calls++
				if !destination.IsValid() || destination.Port() != 22 {
					t.Fatal("resolved destination changed")
				}
				left, right := net.Pipe()
				other = right
				return left, nil
			}
			conn, err := dialNetstackOnly(context.Background(), d, tc.address)
			if (err == nil) != tc.allowed || (conn != nil) != tc.allowed {
				t.Fatal("unexpected route selection")
			}
			if systemCalls != 0 || resolutions > 1 || (calls == 1) != tc.allowed {
				t.Fatal("system dial, duplicate resolution, or unapproved netstack dial")
			}
			if conn != nil {
				conn.Close()
				other.Close()
			}
		})
	}
}

func TestNetstackRouteWithdrawalCannotFallBackToSystem(t *testing.T) {
	peer := netip.MustParseAddr("100.64.0.2")
	approved := true
	routeChecks, names, netstackCalls, systemCalls := 0, 0, 0, 0
	d := &tsdial.Dialer{UseNetstackForIP: func(ip netip.Addr) bool {
		routeChecks++
		wasApproved := approved
		approved = false // Withdraw immediately after this plan's route snapshot.
		return wasApproved && ip == peer
	}}
	d.SetResolveMagicDNS(func(string, string) (netip.Addr, bool) {
		names++
		if names > 1 {
			return netip.MustParseAddr("198.51.100.1"), true
		}
		return peer, true
	})
	d.SetSystemDialerForTest(func(context.Context, string, string) (net.Conn, error) {
		systemCalls++
		return nil, errors.New("forbidden system dial")
	})
	gone := errors.New("synthetic route withdrawn")
	d.NetstackDialTCP = func(_ context.Context, ip netip.AddrPort) (net.Conn, error) {
		netstackCalls++
		if ip.Addr() != peer || approved {
			t.Fatal("plan destination or withdrawal boundary changed")
		}
		return nil, gone
	}
	if _, err := dialNetstackOnly(context.Background(), d, "peer:22"); !errors.Is(err, gone) {
		t.Fatal("netstack error was replaced or retried")
	}
	if names != 1 || routeChecks != 1 || netstackCalls != 1 || systemCalls != 0 {
		t.Fatal("route withdrawal retried resolution/routing or reached the system")
	}
}

func TestNetstackOnlyDialFailsClosedBeforeStartAndWithoutCallback(t *testing.T) {
	e := &tsEngine{server: &tsnet.Server{}}
	if _, err := e.Dial(context.Background(), "100.64.0.2:22"); err == nil {
		t.Fatal("unstarted server was admitted")
	}
	d := &tsdial.Dialer{}
	d.SetResolveMagicDNS(func(string, string) (netip.Addr, bool) {
		t.Fatal("unavailable netstack should not resolve")
		return netip.Addr{}, false
	})
	if _, err := dialNetstackOnly(context.Background(), d, "peer:22"); err == nil {
		t.Fatal("missing netstack callback was admitted")
	}
}
