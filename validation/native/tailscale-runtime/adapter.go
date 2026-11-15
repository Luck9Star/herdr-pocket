package main

import (
	"context"
	"errors"
	"net"
	"sync"
	"tailscale.com/client/local"
	"tailscale.com/envknob"
	"tailscale.com/ipn"
	"tailscale.com/logtail"
	"tailscale.com/net/tsdial"
	"tailscale.com/tsnet"
)

// This adapter deliberately requires the pinned ExplicitAuthOnly source patch.
// Stock tsnet silently falls back to environment auth and interactive login.
type tsEngine struct {
	server *tsnet.Server
	local  *local.Client
}
type tsStore struct{ store stateStore }

func (s tsStore) ReadState(key ipn.StateKey) ([]byte, error) {
	data, found, err := s.store.Read(string(key))
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, ipn.ErrStateNotExist
	}
	if data == nil {
		return []byte{}, nil
	}
	return data, nil
}
func (s tsStore) WriteState(key ipn.StateKey, value []byte) error {
	return s.store.Write(string(key), value, value == nil)
}

var disableLogs sync.Once

func makeTSEngine(c config, store stateStore) engine {
	disableLogs.Do(func() { envknob.SetNoLogsNoSupport(); logtail.Disable() })
	return &tsEngine{server: &tsnet.Server{Dir: c.Directory, Hostname: c.Hostname, ControlURL: c.ControlURL, Store: tsStore{store}, ExplicitAuthOnly: true, Logf: func(string, ...any) {}, UserLogf: func(string, ...any) {}}}
}
func (e *tsEngine) Start() error {
	if err := e.server.Start(); err != nil {
		return err
	}
	lc, err := e.server.LocalClient()
	if err == nil {
		e.local = lc
	}
	return err
}
func (e *tsEngine) Status(ctx context.Context) (snapshot, error) {
	s, err := e.local.StatusWithoutPeers(ctx)
	if err != nil {
		return snapshot{}, err
	}
	return snapshot{State: s.BackendState, AuthURL: s.AuthURL}, nil
}
func (e *tsEngine) Login(ctx context.Context) error { return e.local.StartLoginInteractive(ctx) }
func (e *tsEngine) Dial(ctx context.Context, address string) (net.Conn, error) {
	// Sys is intentionally unstable upstream; its exact source is pinned and
	// verified by tailscale_candidate.py. Manager lifetime gates ensure Start
	// has completed and prevent Close until this operation drains.
	system := e.server.Sys()
	if system == nil {
		return nil, errors.New("Tailscale dialer unavailable")
	}
	dialer, ok := system.Dialer.GetOK()
	if !ok || dialer == nil {
		return nil, errors.New("Tailscale dialer unavailable")
	}
	return dialNetstackOnly(ctx, dialer, address)
}

func dialNetstackOnly(ctx context.Context, dialer *tsdial.Dialer, address string) (net.Conn, error) {
	dial := dialer.NetstackDialTCP
	if dial == nil {
		return nil, errors.New("Tailscale netstack unavailable")
	}
	resolved, routed, err := dialer.UserDialPlanWithoutDNSFallback(ctx, "tcp", address)
	if err != nil || !routed || !resolved.IsValid() {
		return nil, errors.New("target not routed through selected Tailscale node")
	}
	// Do not call Server.Dial/UserDial after validation: even an IP literal can
	// fall back to a system socket if its route is withdrawn between calls.
	return dial(ctx, resolved)
}
func (e *tsEngine) Close() error { return e.server.Close() }
