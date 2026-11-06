package main

import (
	"context"
	"net"
	"sync"
	"tailscale.com/client/local"
	"tailscale.com/envknob"
	"tailscale.com/ipn"
	"tailscale.com/logtail"
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
	return e.server.Dial(ctx, "tcp", address)
}
func (e *tsEngine) Close() error { return e.server.Close() }
