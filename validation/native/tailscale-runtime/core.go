package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

type code int32

const (
	ok code = iota
	invalid
	notFound
	busy
	limit
	timedOut
	cancelled
	notRunning
	ioError
	unknownWrite
	bufferSmall
	unsupported
)
const maxIO = 65536
const maxTimeout = 60000
const defaultControl = "https://controlplane.tailscale.com"

type stateStore interface {
	Read(string) ([]byte, bool, error)
	Write(string, []byte, bool) error
}

// A node owns this gate independently of engine shutdown guarantees. Every
// host callback (including cStore's allocation release) completes under a
// shared lease. Retirement waits existing leases and excludes future calls.
type gatedStore struct {
	mu         sync.RWMutex
	closed     bool
	underlying stateStore
}

var errStoreRetired = errors.New("state store retired")

func (s *gatedStore) Read(key string) ([]byte, bool, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.closed || s.underlying == nil {
		return nil, false, errStoreRetired
	}
	return s.underlying.Read(key)
}
func (s *gatedStore) Write(key string, data []byte, deleted bool) error {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.closed || s.underlying == nil {
		return errStoreRetired
	}
	return s.underlying.Write(key, data, deleted)
}
func (s *gatedStore) retire() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.closed = true
	s.underlying = nil
}

type config struct {
	Directory  string `json:"directory"`
	Hostname   string `json:"hostname"`
	ControlURL string `json:"control_url"`
}
type snapshot struct {
	State   string `json:"state"`
	AuthURL string `json:"auth_url"`
}
type engine interface {
	Start() error
	Status(context.Context) (snapshot, error)
	Login(context.Context) error
	Dial(context.Context, string) (net.Conn, error)
	Close() error
}
type factory func(config, stateStore) engine

type manager struct {
	mu         sync.Mutex
	next       uint64
	nodes      map[uint64]*node
	streams    map[uint64]*stream
	makeEngine factory
}
type closeAttempt struct {
	done chan struct{}
	err  error
}
type node struct {
	mu                                   sync.Mutex
	id                                   uint64
	directory                            string
	engine                               engine
	store                                *gatedStore
	started, closing, login, controlBusy bool
	startDone, closeDone                 chan struct{}
	startErr                             error
	closeAttempt                         *closeAttempt
	ctx                                  context.Context
	cancel                               context.CancelFunc
	ops                                  sync.WaitGroup
}
type stream struct {
	mu                        sync.Mutex
	id, owner                 uint64
	conn                      net.Conn
	closeAttempt              *closeAttempt
	orphan                    bool
	closing, reading, writing bool
	closeDone                 chan struct{}
	ready                     chan struct{}
	retired                   chan struct{}
	ops                       sync.WaitGroup
}

func newManager(f factory) *manager {
	return &manager{nodes: map[uint64]*node{}, streams: map[uint64]*stream{}, makeEngine: f}
}
func (m *manager) alloc() uint64 {
	if m.next == ^uint64(0) {
		return 0
	}
	m.next++
	return m.next
}
func validTimeout(ms uint32) bool { return ms > 0 && ms <= maxTimeout }
func timeout(ms uint32) (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), time.Duration(ms)*time.Millisecond)
}
func (m *manager) getNode(id uint64) *node { m.mu.Lock(); defer m.mu.Unlock(); return m.nodes[id] }
func (m *manager) getStream(id uint64) *stream {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.streams[id]
}
func parseConfig(data []byte) (config, error) {
	var c config
	d := json.NewDecoder(strings.NewReader(string(data)))
	d.DisallowUnknownFields()
	if err := d.Decode(&c); err != nil {
		return c, err
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return c, errors.New("extra JSON")
	}
	if c.Hostname == "" {
		c.Hostname = "herdr-pocket"
	}
	if c.ControlURL == "" {
		c.ControlURL = defaultControl
	}
	u, e := url.Parse(c.ControlURL)
	if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Fragment != "" || u.RawQuery != "" || len(c.ControlURL) > 4096 || !filepath.IsAbs(c.Directory) || filepath.Clean(c.Directory) != c.Directory || strings.ContainsRune(c.Directory, 0) || strings.ContainsRune(c.Hostname, 0) || len(c.Directory) > 4096 || len(c.Hostname) > 253 {
		return c, errors.New("invalid config")
	}
	return c, nil
}
func (m *manager) newNode(c config, store stateStore) (uint64, code) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.nodes) >= 8 {
		return 0, limit
	}
	for _, n := range m.nodes {
		if n.directory == c.Directory {
			return 0, busy
		}
	}
	id := m.alloc()
	if id == 0 {
		return 0, limit
	}
	ctx, cancel := context.WithCancel(context.Background())
	gate := &gatedStore{underlying: store}
	m.nodes[id] = &node{id: id, directory: c.Directory, store: gate, engine: m.makeEngine(c, gate), ctx: ctx, cancel: cancel, startDone: make(chan struct{}), closeDone: make(chan struct{})}
	return id, ok
}
func (m *manager) start(id uint64, ms uint32) code {
	if !validTimeout(ms) {
		return invalid
	}
	n := m.getNode(id)
	if n == nil {
		return notFound
	}
	n.mu.Lock()
	if n.closing {
		n.mu.Unlock()
		return cancelled
	}
	if !n.started {
		n.started = true
		go func() {
			err := n.engine.Start()
			n.mu.Lock()
			n.startErr = err
			close(n.startDone)
			n.mu.Unlock()
			if err != nil {
				m.closeNode(n, false)
			}
		}()
	}
	n.mu.Unlock()
	ctx, cancel := timeout(ms)
	defer cancel()
	select {
	case <-n.startDone:
		n.mu.Lock()
		defer n.mu.Unlock()
		if n.startErr != nil {
			return ioError
		}
		if n.closing {
			return cancelled
		}
		return ok
	case <-ctx.Done():
		m.closeNode(n, false)
		return timedOut
	case <-n.ctx.Done():
		return cancelled
	}
}
func (m *manager) closeNode(n *node, retry bool) *closeAttempt {
	n.mu.Lock()
	if n.closeAttempt != nil {
		a := n.closeAttempt
		select {
		case <-a.done:
			if a.err == nil || !retry {
				n.mu.Unlock()
				return a
			}
		default:
			n.mu.Unlock()
			return a
		}
	}
	first := !n.closing
	n.closing = true
	if first {
		n.cancel()
	}
	started := n.started
	a := &closeAttempt{done: make(chan struct{})}
	n.closeAttempt = a
	n.mu.Unlock()
	go func() {
		if started {
			<-n.startDone
		}
		type closingStream struct {
			s *stream
			a *closeAttempt
		}
		closing := map[uint64]closingStream{}
		collect := func() {
			m.mu.Lock()
			var ss []*stream
			for _, s := range m.streams {
				if s.owner == n.id {
					ss = append(ss, s)
				}
			}
			m.mu.Unlock()
			for _, s := range ss {
				if _, yes := closing[s.id]; !yes {
					closing[s.id] = closingStream{s, m.closeStream(s, retry)}
				}
			}
		}
		collect() // interrupt existing IO before waiting for node operations
		n.ops.Wait()
		collect() // a reserved Dial may have appeared during first snapshot
		for _, entry := range closing {
			<-entry.a.done
			if entry.a.err != nil {
				a.err = errors.New("stream close failed")
			} else {
				m.removeOrphan(entry.s)
			}
		}
		if a.err == nil && started {
			a.err = n.engine.Close()
		}
		if a.err == nil {
			n.store.retire()
			close(n.closeDone)
		}
		close(a.done)
	}()
	return a
}
func waitAttempt(a *closeAttempt, ms uint32) code {
	if !validTimeout(ms) {
		return invalid
	}
	ctx, cancel := timeout(ms)
	defer cancel()
	select {
	case <-a.done:
		if a.err != nil {
			return ioError
		}
		return ok
	case <-ctx.Done():
		return timedOut
	}
}
func (m *manager) nodeClose(id uint64, ms uint32) code {
	if !validTimeout(ms) {
		return invalid
	}
	n := m.getNode(id)
	if n == nil {
		return notFound
	}
	return waitAttempt(m.closeNode(n, true), ms)
}
func (m *manager) nodeCancel(id uint64) code {
	n := m.getNode(id)
	if n == nil {
		return notFound
	}
	m.closeNode(n, false)
	return ok
}
func (m *manager) nodeRelease(id uint64) code {
	m.mu.Lock()
	defer m.mu.Unlock()
	n := m.nodes[id]
	if n == nil {
		return notFound
	}
	select {
	case <-n.closeDone:
	default:
		return busy
	}
	for _, s := range m.streams {
		if s.owner == id {
			return busy
		}
	}
	delete(m.nodes, id)
	return ok
}
func safeSnapshot(s snapshot, login bool) snapshot {
	switch s.State {
	case "Starting", "NeedsLogin", "NeedsMachineAuth", "Running", "Stopped":
	default:
		s.State = "Starting"
	}
	if !login {
		s.AuthURL = ""
	}
	if s.AuthURL != "" {
		u, e := url.Parse(s.AuthURL)
		if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Fragment != "" || len(s.AuthURL) > 4096 {
			s.AuthURL = ""
		}
	}
	return s
}

type controlResult struct {
	s   snapshot
	err error
}

func (m *manager) control(id uint64, ms uint32, login bool) (snapshot, code) {
	if !validTimeout(ms) {
		return snapshot{}, invalid
	}
	n := m.getNode(id)
	if n == nil {
		return snapshot{}, notFound
	}
	n.mu.Lock()
	if n.closing {
		if login {
			n.mu.Unlock()
			return snapshot{}, cancelled
		}
		select {
		case <-n.closeDone:
			n.mu.Unlock()
			return snapshot{State: "Stopped"}, ok
		default:
			n.mu.Unlock()
			return snapshot{State: "Closing"}, ok
		}
	}
	if !n.started {
		n.mu.Unlock()
		if login {
			return snapshot{State: "Stopped"}, notRunning
		}
		return snapshot{State: "Stopped"}, ok
	}
	select {
	case <-n.startDone:
	default:
		n.mu.Unlock()
		if login {
			return snapshot{State: "Starting"}, notRunning
		}
		return snapshot{State: "Starting"}, ok
	}
	if n.startErr != nil {
		n.mu.Unlock()
		return snapshot{State: "Stopped"}, ioError
	}
	if n.controlBusy {
		n.mu.Unlock()
		return snapshot{}, busy
	}
	n.controlBusy = true
	if login {
		n.login = true
	}
	allowed := n.login
	n.ops.Add(1)
	n.mu.Unlock()
	ctx, cancel := context.WithTimeout(n.ctx, time.Duration(ms)*time.Millisecond)
	defer cancel()
	ch := make(chan controlResult, 1)
	go func() {
		defer n.ops.Done()
		defer func() { n.mu.Lock(); n.controlBusy = false; n.mu.Unlock() }()
		if login {
			if e := n.engine.Login(ctx); e != nil {
				ch <- controlResult{err: e}
				return
			}
		}
		s, e := n.engine.Status(ctx)
		ch <- controlResult{s, e}
	}()
	select {
	case r := <-ch:
		if r.err != nil {
			return snapshot{}, ioError
		}
		return safeSnapshot(r.s, allowed), ok
	case <-ctx.Done():
		if n.ctx.Err() != nil {
			return snapshot{}, cancelled
		}
		return snapshot{}, timedOut
	}
}
func (m *manager) dial(id uint64, address string, ms uint32) (uint64, code) {
	if !validTimeout(ms) || len(address) > 4096 {
		return 0, invalid
	}
	h, p, e := net.SplitHostPort(address)
	port, portErr := strconv.Atoi(p)
	if e != nil || h == "" || strings.ContainsRune(h, 0) || portErr != nil || port < 1 || port > 65535 {
		return 0, invalid
	}
	until := time.Now().Add(time.Duration(ms) * time.Millisecond)
	st, c := m.control(id, ms, false)
	if c != ok {
		return 0, c
	}
	if st.State != "Running" {
		return 0, notRunning
	}
	n := m.getNode(id)
	if n == nil {
		return 0, notFound
	}
	n.mu.Lock()
	if n.closing {
		n.mu.Unlock()
		return 0, cancelled
	}
	n.ops.Add(1)
	n.mu.Unlock()
	m.mu.Lock()
	if len(m.streams) >= 32 {
		m.mu.Unlock()
		n.ops.Done()
		return 0, limit
	}
	sid := m.alloc()
	if sid == 0 {
		m.mu.Unlock()
		n.ops.Done()
		return 0, limit
	}
	s := &stream{id: sid, owner: id, orphan: true, closeDone: make(chan struct{}), ready: make(chan struct{})}
	m.streams[sid] = s
	m.mu.Unlock()
	ctx, cancel := context.WithDeadline(n.ctx, until)
	defer cancel()
	type result struct {
		conn net.Conn
		err  error
	}
	ch := make(chan result)
	go func() {
		defer n.ops.Done()
		conn, e := n.engine.Dial(ctx, address)
		if e == nil && conn == nil {
			e = errors.New("nil conn")
		}
		s.mu.Lock()
		s.conn = conn
		close(s.ready)
		s.mu.Unlock()
		if e == nil {
			select {
			case ch <- result{conn, nil}:
				return
			case <-ctx.Done():
			}
		}
		attempt := m.closeStream(s, false)
		<-attempt.done
		m.removeOrphan(s)
		select {
		case ch <- result{err: e}:
		case <-ctx.Done():
		}
	}()
	select {
	case r := <-ch:
		if r.err != nil {
			return 0, ioError
		}
		n.mu.Lock()
		closing := n.closing
		if !closing {
			s.mu.Lock()
			s.orphan = false
			s.mu.Unlock()
		}
		n.mu.Unlock()
		if closing {
			m.closeStream(s, false)
			go func() { attempt := m.closeStream(s, false); <-attempt.done; m.removeOrphan(s) }()
			return 0, cancelled
		}
		return sid, ok
	case <-ctx.Done():
		if n.ctx.Err() != nil {
			return 0, cancelled
		}
		return 0, timedOut
	}
}
func (m *manager) closeStream(s *stream, retry bool) *closeAttempt {
	s.mu.Lock()
	if s.closeAttempt != nil {
		a := s.closeAttempt
		select {
		case <-a.done:
			if a.err == nil || !retry {
				s.mu.Unlock()
				return a
			}
		default:
			s.mu.Unlock()
			return a
		}
	}
	if !s.closing {
		s.closing = true
		if s.retired == nil {
			s.retired = make(chan struct{})
		}
		close(s.retired)
	}
	a := &closeAttempt{done: make(chan struct{})}
	s.closeAttempt = a
	s.mu.Unlock()
	go func() {
		if s.ready != nil {
			<-s.ready
		}
		s.mu.Lock()
		conn := s.conn
		s.mu.Unlock()
		if conn != nil {
			a.err = conn.Close()
		}
		if a.err == nil {
			s.ops.Wait()
			close(s.closeDone)
		}
		close(a.done)
	}()
	return a
}
func (m *manager) removeOrphan(s *stream) {
	s.mu.Lock()
	orphan := s.orphan
	s.mu.Unlock()
	if !orphan {
		return
	}
	select {
	case <-s.closeDone:
		m.mu.Lock()
		if m.streams[s.id] == s {
			delete(m.streams, s.id)
		}
		m.mu.Unlock()
	default:
	}
}
func (m *manager) streamCancel(id uint64) code {
	s := m.getStream(id)
	if s == nil {
		return notFound
	}
	m.closeStream(s, false)
	return ok
}
func (m *manager) streamClose(id uint64, ms uint32) code {
	if !validTimeout(ms) {
		return invalid
	}
	s := m.getStream(id)
	if s == nil {
		return notFound
	}
	return waitAttempt(m.closeStream(s, true), ms)
}
func (m *manager) streamRelease(id uint64) code {
	m.mu.Lock()
	defer m.mu.Unlock()
	s := m.streams[id]
	if s == nil {
		return notFound
	}
	select {
	case <-s.closeDone:
		delete(m.streams, id)
		return ok
	default:
		return busy
	}
}

type ioResult struct {
	n    int
	err  error
	data []byte
}

func (m *manager) streamIO(id uint64, data []byte, size int, ms uint32, write, half bool) ([]byte, int, code) {
	if !validTimeout(ms) || size < 0 || size > maxIO {
		return nil, 0, invalid
	}
	s := m.getStream(id)
	if s == nil {
		return nil, 0, notFound
	}
	s.mu.Lock()
	if s.closing || s.conn == nil {
		s.mu.Unlock()
		return nil, 0, cancelled
	}
	if (write && s.writing) || (!write && s.reading) {
		s.mu.Unlock()
		return nil, 0, busy
	}
	if half {
		if _, yes := s.conn.(interface{ CloseWrite() error }); !yes {
			s.mu.Unlock()
			return nil, 0, unsupported
		}
	}
	if write {
		s.writing = true
	} else {
		s.reading = true
	}
	s.ops.Add(1)
	if s.retired == nil {
		s.retired = make(chan struct{})
	}
	retired := s.retired
	conn := s.conn
	s.mu.Unlock()
	ctx, cancel := timeout(ms)
	defer cancel()
	ch := make(chan ioResult, 1)
	go func() {
		defer s.ops.Done()
		defer func() {
			s.mu.Lock()
			if write {
				s.writing = false
			} else {
				s.reading = false
			}
			s.mu.Unlock()
		}()
		deadline, _ := ctx.Deadline()
		var r ioResult
		if write {
			if e := conn.SetWriteDeadline(deadline); e != nil {
				r.err = e
			} else if half {
				r.err = conn.(interface{ CloseWrite() error }).CloseWrite()
			} else {
				r.n, r.err = conn.Write(data)
			}
		} else {
			r.data = make([]byte, size)
			if e := conn.SetReadDeadline(deadline); e != nil {
				r.err = e
			} else {
				r.n, r.err = conn.Read(r.data)
			}
		}
		ch <- r
	}()
	select {
	case r := <-ch:
		if r.err == nil || (!write && errors.Is(r.err, io.EOF)) {
			return r.data, r.n, ok
		}
		if write {
			m.closeStream(s, false)
			return nil, r.n, unknownWrite
		}
		if e, yes := r.err.(net.Error); yes && e.Timeout() && r.n == 0 {
			return nil, 0, timedOut
		}
		m.closeStream(s, false)
		return r.data, r.n, ioError
	case <-retired:
		if write {
			return nil, 0, unknownWrite
		}
		return nil, 0, cancelled
	case <-ctx.Done():
		m.closeStream(s, false)
		if write {
			return nil, 0, unknownWrite
		}
		return nil, 0, cancelled
	}
}
