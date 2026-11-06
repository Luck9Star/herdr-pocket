package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeEngine struct {
	start                         func() error
	status                        func(context.Context) (snapshot, error)
	login                         func(context.Context) error
	dial                          func(context.Context, string) (net.Conn, error)
	close                         func() error
	starts, logins, dials, closes atomic.Int32
}

func (f *fakeEngine) Start() error {
	f.starts.Add(1)
	if f.start != nil {
		return f.start()
	}
	return nil
}
func (f *fakeEngine) Status(ctx context.Context) (snapshot, error) {
	if f.status != nil {
		return f.status(ctx)
	}
	return snapshot{State: "Running"}, nil
}
func (f *fakeEngine) Login(ctx context.Context) error {
	f.logins.Add(1)
	if f.login != nil {
		return f.login(ctx)
	}
	return nil
}
func (f *fakeEngine) Dial(ctx context.Context, a string) (net.Conn, error) {
	f.dials.Add(1)
	if f.dial != nil {
		return f.dial(ctx, a)
	}
	return nil, errors.New("not configured")
}
func (f *fakeEngine) Close() error {
	f.closes.Add(1)
	if f.close != nil {
		return f.close()
	}
	return nil
}

type memoryStore struct {
	mu     sync.Mutex
	values map[string][]byte
}

func (s *memoryStore) Read(k string) ([]byte, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	v, yes := s.values[k]
	return append([]byte{}, v...), yes, nil
}
func (s *memoryStore) Write(k string, v []byte, d bool) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if d {
		delete(s.values, k)
	} else {
		s.values[k] = append([]byte{}, v...)
	}
	return nil
}
func managerWith(f *fakeEngine) *manager {
	return newManager(func(config, stateStore) engine { return f })
}
func addNode(t *testing.T, m *manager, d string) uint64 {
	t.Helper()
	id, c := m.newNode(config{Directory: d, ControlURL: defaultControl}, &memoryStore{values: map[string][]byte{}})
	if c != ok {
		t.Fatalf("new: %v", c)
	}
	return id
}
func addStream(m *manager, n uint64, c net.Conn) uint64 {
	m.mu.Lock()
	defer m.mu.Unlock()
	id := m.alloc()
	ready := make(chan struct{})
	close(ready)
	m.streams[id] = &stream{id: id, owner: n, conn: c, ready: ready, closeDone: make(chan struct{})}
	return id
}
func eventually(t *testing.T, f func() bool) {
	t.Helper()
	until := time.Now().Add(time.Second)
	for !f() {
		if time.Now().After(until) {
			t.Fatal("condition did not settle")
		}
		time.Sleep(time.Millisecond)
	}
}
func closeNode(t *testing.T, m *manager, id uint64) {
	t.Helper()
	if c := m.nodeClose(id, 1000); c != ok {
		t.Fatalf("node close=%v", c)
	}
	m.mu.Lock()
	var ss []uint64
	for sid, s := range m.streams {
		if s.owner == id {
			ss = append(ss, sid)
		}
	}
	m.mu.Unlock()
	for _, sid := range ss {
		if c := m.streamRelease(sid); c != ok {
			t.Fatalf("stream release %v", c)
		}
	}
	if c := m.nodeRelease(id); c != ok {
		t.Fatalf("node release %v", c)
	}
}
func TestStartTimeoutRetainsQuotaAndSerializesClose(t *testing.T) {
	gate := make(chan struct{})
	entered := make(chan struct{})
	f := &fakeEngine{start: func() error { close(entered); <-gate; return nil }}
	m := managerWith(f)
	id := addNode(t, m, "one")
	if c := m.start(id, 10); c != timedOut {
		t.Fatalf("start %v", c)
	}
	<-entered
	if f.closes.Load() != 0 || m.nodeRelease(id) != busy {
		t.Fatal("released before Start settled")
	}
	for i := 0; i < 7; i++ {
		addNode(t, m, fmt.Sprint(i))
	}
	if _, c := m.newNode(config{Directory: "ninth"}, nil); c != limit {
		t.Fatalf("quota %v", c)
	}
	if m.nodeClose(id, 5) != timedOut {
		t.Fatal("close did not retain start")
	}
	close(gate)
	eventually(t, func() bool { return f.closes.Load() == 1 })
	if m.nodeClose(id, 1000) != ok || m.nodeRelease(id) != ok {
		t.Fatal("cleanup failed")
	}
	if m.start(id, 1) != notFound {
		t.Fatal("old handle reusable")
	}
	id2 := addNode(t, m, "replacement")
	if id2 <= id {
		t.Fatal("reused handle")
	}
	if f.closes.Load() != 1 {
		t.Fatal("close called twice")
	}
}
func TestCloseWithoutStartNeverCallsEngineClose(t *testing.T) {
	f := &fakeEngine{}
	m := managerWith(f)
	id := addNode(t, m, "x")
	closeNode(t, m, id)
	if f.starts.Load() != 0 || f.closes.Load() != 0 {
		t.Fatal("unstarted engine touched")
	}
}
func TestFailedStartStillClosedAndRetained(t *testing.T) {
	gate := make(chan struct{})
	f := &fakeEngine{start: func() error { return errors.New("fail") }, close: func() error { <-gate; return nil }}
	m := managerWith(f)
	id := addNode(t, m, "x")
	c := m.start(id, 100)
	if c != ioError && c != cancelled {
		t.Fatalf("start=%v", c)
	}
	if m.nodeRelease(id) != busy {
		t.Fatal("failed node freed early")
	}
	close(gate)
	closeNode(t, m, id)
}
func TestStatusDoesNotEquateStartWithRunningAndLoginExplicit(t *testing.T) {
	var state atomic.Value
	state.Store("NeedsLogin")
	f := &fakeEngine{status: func(context.Context) (snapshot, error) {
		return snapshot{State: state.Load().(string), AuthURL: "https://login.tailscale.com/a/secret"}, nil
	}}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	s, c := m.control(id, 1000, false)
	if c != ok || s.State != "NeedsLogin" || s.AuthURL != "" || f.logins.Load() != 0 {
		t.Fatalf("unexpected %+v %v", s, c)
	}
	if _, c = m.dial(id, "100.64.0.1:22", 1000); c != notRunning || f.dials.Load() != 0 {
		t.Fatal("dial before Running")
	}
	eventually(t, func() bool { _, c = m.control(id, 1000, true); return c == ok })
	if f.logins.Load() != 1 {
		t.Fatal("login not explicit once")
	}
	eventually(t, func() bool { s, c = m.control(id, 1000, false); return c == ok })
	if s.AuthURL == "" {
		t.Fatal("missing explicit URL")
	}
	for _, v := range []string{"NeedsMachineAuth", "Starting", "Running", "Stopped"} {
		state.Store(v)
		eventually(t, func() bool { s, c = m.control(id, 1000, false); return c == ok })
		if s.State != v {
			t.Fatal(s)
		}
	}
	closeNode(t, m, id)
}
func TestAuthURLValidation(t *testing.T) {
	for _, u := range []string{"http://login.tailscale.com/a", "https://u:p@login.tailscale.com/a", "https://login.tailscale.com/a#x", ":bad"} {
		if s := safeSnapshot(snapshot{State: "Running", AuthURL: u}, true); s.AuthURL != "" {
			t.Fatal(u)
		}
	}
	if safeSnapshot(snapshot{State: "invalid"}, true).State != "Starting" {
		t.Fatal("unrecognized state")
	}
}
func TestControlTimeoutRetainsEngineUntilLateCallback(t *testing.T) {
	gate := make(chan struct{})
	f := &fakeEngine{login: func(context.Context) error { <-gate; return nil }}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	_, c := m.control(id, 5, true)
	if c != timedOut {
		t.Fatal(c)
	}
	if m.nodeClose(id, 5) != timedOut || m.nodeRelease(id) != busy || f.closes.Load() != 0 {
		t.Fatal("callback owner released early")
	}
	close(gate)
	closeNode(t, m, id)
}
func TestNetPipeReadWriteParallelAndSingleFlight(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	left, right := net.Pipe()
	defer right.Close()
	sid := addStream(m, id, left)
	readResult := make(chan code, 1)
	go func() {
		b, n, c := m.streamIO(sid, nil, 10, 1000, false, false)
		if n != 3 || string(b[:n]) != "abc" {
			readResult <- ioError
			return
		}
		readResult <- c
	}()
	eventually(t, func() bool { s := m.getStream(sid); s.mu.Lock(); defer s.mu.Unlock(); return s.reading })
	if _, _, c := m.streamIO(sid, nil, 1, 10, false, false); c != busy {
		t.Fatal("second read allowed")
	}
	peer := make(chan error, 1)
	go func() {
		b := make([]byte, 3)
		_, e := io.ReadFull(right, b)
		if e == nil && string(b) != "xyz" {
			e = errors.New("wrong write")
		}
		if e == nil {
			_, e = right.Write([]byte("abc"))
		}
		peer <- e
	}()
	if _, n, c := m.streamIO(sid, []byte("xyz"), 3, 1000, true, false); c != ok || n != 3 {
		t.Fatalf("write %d %v", n, c)
	}
	if c := <-readResult; c != ok {
		t.Fatal(c)
	}
	if e := <-peer; e != nil {
		t.Fatal(e)
	}
	closeNode(t, m, id)
}

type stubbornConn struct {
	readGate, writeGate, closeGate chan struct{}
	readEntered, writeEntered      chan struct{}
	reads, writes, closes          atomic.Int32
}

func (c *stubbornConn) Read(b []byte) (int, error) {
	if c.reads.Add(1) == 1 && c.readEntered != nil {
		close(c.readEntered)
	}
	if c.readGate != nil {
		<-c.readGate
	}
	if len(b) > 0 {
		b[0] = 'L'
		return 1, nil
	}
	return 0, nil
}
func (c *stubbornConn) Write(b []byte) (int, error) {
	if c.writes.Add(1) == 1 && c.writeEntered != nil {
		close(c.writeEntered)
	}
	if c.writeGate != nil {
		<-c.writeGate
	}
	return len(b), nil
}
func (c *stubbornConn) Close() error {
	c.closes.Add(1)
	if c.closeGate != nil {
		<-c.closeGate
	}
	return nil
}
func (c *stubbornConn) LocalAddr() net.Addr              { return &net.TCPAddr{} }
func (c *stubbornConn) RemoteAddr() net.Addr             { return &net.TCPAddr{} }
func (c *stubbornConn) SetDeadline(time.Time) error      { return nil }
func (c *stubbornConn) SetReadDeadline(time.Time) error  { return nil }
func (c *stubbornConn) SetWriteDeadline(time.Time) error { return nil }
func TestUnsettledReadTimeoutRetiresRatherThanRetry(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	c := &stubbornConn{readGate: make(chan struct{}), readEntered: make(chan struct{})}
	sid := addStream(m, id, c)
	if _, _, rc := m.streamIO(sid, nil, 1, 10, false, false); rc != cancelled {
		t.Fatalf("unfinished read reported retryable: %v", rc)
	}
	<-c.readEntered
	if m.streamRelease(sid) != busy {
		t.Fatal("released in-flight Read")
	}
	if _, _, rc := m.streamIO(sid, nil, 1, 10, false, false); rc != cancelled || c.reads.Load() != 1 {
		t.Fatal("retried read")
	}
	close(c.readGate)
	if m.streamClose(sid, 1000) != ok || m.streamRelease(sid) != ok {
		t.Fatal("late Read cleanup")
	}
	closeNode(t, m, id)
}
func TestUnknownWriteNeverReplaysAndLateCloseHoldsQuota(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	c := &stubbornConn{writeGate: make(chan struct{}), writeEntered: make(chan struct{}), closeGate: make(chan struct{})}
	sid := addStream(m, id, c)
	if _, _, rc := m.streamIO(sid, []byte("input"), 5, 10, true, false); rc != unknownWrite {
		t.Fatal(rc)
	}
	<-c.writeEntered
	if m.streamClose(sid, 5) != timedOut || m.streamRelease(sid) != busy {
		t.Fatal("early release")
	}
	if _, _, rc := m.streamIO(sid, []byte("input"), 5, 10, true, false); rc != cancelled || c.writes.Load() != 1 {
		t.Fatal("replayed")
	}
	for i := 0; i < 31; i++ {
		a, b := net.Pipe()
		defer b.Close()
		addStream(m, id, a)
	}
	if _, rc := m.dial(id, "100.64.0.1:22", 10); rc != notRunning {
		t.Fatal("unstarted node")
	}
	m.mu.Lock()
	n := len(m.streams)
	m.mu.Unlock()
	if n != 32 {
		t.Fatal(n)
	}
	close(c.writeGate)
	if m.streamRelease(sid) != busy {
		t.Fatal("freed before Close settled")
	}
	close(c.closeGate)
	closeNode(t, m, id)
}
func TestLateDialSuccessClosedBeforeQuotaRelease(t *testing.T) {
	gate := make(chan struct{})
	late := &stubbornConn{closeGate: make(chan struct{})}
	f := &fakeEngine{dial: func(context.Context, string) (net.Conn, error) { <-gate; return late, nil }}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	if sid, c := m.dial(id, "100.64.0.1:22", 10); c != timedOut || sid != 0 {
		t.Fatalf("dial %d %v", sid, c)
	}
	m.mu.Lock()
	count := len(m.streams)
	m.mu.Unlock()
	if count != 1 {
		t.Fatal("pending dial quota freed")
	}
	if m.nodeClose(id, 5) != timedOut || m.nodeRelease(id) != busy {
		t.Fatal("node freed pending dial")
	}
	close(gate)
	eventually(t, func() bool { return late.closes.Load() == 1 })
	if m.nodeClose(id, 5) != timedOut {
		t.Fatal("node released before late conn.Close")
	}
	close(late.closeGate)
	eventually(t, func() bool { m.mu.Lock(); defer m.mu.Unlock(); return len(m.streams) == 0 })
	closeNode(t, m, id)
}
func TestStreamQuotaAndMonotonicIDs(t *testing.T) {
	var peers []net.Conn
	f := &fakeEngine{dial: func(context.Context, string) (net.Conn, error) {
		a, b := net.Pipe()
		peers = append(peers, b)
		return a, nil
	}}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	var ids []uint64
	for i := 0; i < 32; i++ {
		var sid uint64
		var c code
		eventually(t, func() bool { sid, c = m.dial(id, "100.64.0.1:22", 1000); return c != busy })
		if c != ok {
			t.Fatal(c)
		}
		ids = append(ids, sid)
	}
	eventually(t, func() bool {
		_, c := m.dial(id, "100.64.0.1:22", 1000)
		if c == busy {
			return false
		}
		if c != limit {
			t.Fatalf("quota %v", c)
		}
		return true
	})
	sid := ids[0]
	if m.streamClose(sid, 1000) != ok || m.streamRelease(sid) != ok {
		t.Fatal("close")
	}
	var next uint64
	eventually(t, func() bool { var c code; next, c = m.dial(id, "100.64.0.1:22", 1000); return c == ok })
	if next <= ids[31] {
		t.Fatal("handle reused")
	}
	for _, p := range peers {
		p.Close()
	}
	closeNode(t, m, id)
}
func TestHalfCloseUnsupportedDoesNotFullClose(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	a, b := net.Pipe()
	defer b.Close()
	sid := addStream(m, id, a)
	if _, _, c := m.streamIO(sid, nil, 0, 100, true, true); c != unsupported {
		t.Fatal(c)
	}
	s := m.getStream(sid)
	s.mu.Lock()
	closing := s.closing
	s.mu.Unlock()
	if closing {
		t.Fatal("unsupported half-close fully closed")
	}
	closeNode(t, m, id)
}
func TestValidationAndDirectoryLease(t *testing.T) {
	for _, raw := range []string{`{}`, `{"directory":"/x","auth_key":"secret"}`, `{"directory":"/x"} {}`, `{"directory":"/x","control_url":"http://control.invalid"}`} {
		if _, e := parseConfig([]byte(raw)); e == nil {
			t.Fatal(raw)
		}
	}
	c, e := parseConfig([]byte(`{"directory":"/x"}`))
	if e != nil || c.ControlURL != defaultControl {
		t.Fatal(c, e)
	}
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "same")
	if _, rc := m.newNode(config{Directory: "same"}, nil); rc != busy {
		t.Fatal(rc)
	}
	if m.start(id, 0) != invalid || m.start(id, 60001) != invalid {
		t.Fatal("unbounded deadline")
	}
	if _, _, rc := m.streamIO(0, nil, maxIO+1, 1, false, false); rc != invalid {
		t.Fatal(rc)
	}
	closeNode(t, m, id)
}

type timeoutError struct{}

func (timeoutError) Error() string   { return "deadline" }
func (timeoutError) Timeout() bool   { return true }
func (timeoutError) Temporary() bool { return true }

type settledTimeoutConn struct {
	stubbornConn
	count atomic.Int32
}

func (c *settledTimeoutConn) Read(b []byte) (int, error) {
	if c.count.Add(1) == 1 {
		return 0, timeoutError{}
	}
	b[0] = 'R'
	return 1, nil
}
func TestSettledZeroByteReadTimeoutCanRetry(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	c := &settledTimeoutConn{}
	sid := addStream(m, id, c)
	if _, n, rc := m.streamIO(sid, nil, 1, 1000, false, false); rc != timedOut || n != 0 {
		t.Fatal(n, rc)
	}
	eventually(t, func() bool { s := m.getStream(sid); s.mu.Lock(); defer s.mu.Unlock(); return !s.reading })
	b, n, rc := m.streamIO(sid, nil, 1, 1000, false, false)
	if rc != ok || n != 1 || b[0] != 'R' {
		t.Fatal(n, rc)
	}
	closeNode(t, m, id)
}
func TestParallelWriteSingleFlightAndCancelWake(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	c := &stubbornConn{writeGate: make(chan struct{}), writeEntered: make(chan struct{})}
	sid := addStream(m, id, c)
	res := make(chan code, 1)
	go func() { _, _, rc := m.streamIO(sid, []byte("one"), 3, 60000, true, false); res <- rc }()
	<-c.writeEntered
	if _, _, rc := m.streamIO(sid, []byte("two"), 3, 100, true, false); rc != busy {
		t.Fatal(rc)
	}
	if m.streamCancel(sid) != ok {
		t.Fatal("cancel")
	}
	select {
	case rc := <-res:
		if rc != unknownWrite {
			t.Fatal(rc)
		}
	case <-time.After(time.Second):
		t.Fatal("cancel did not wake waiter while Write remained blocked")
	}
	if m.streamRelease(sid) != busy {
		t.Fatal("early release")
	}
	close(c.writeGate)
	if c.writes.Load() != 1 {
		t.Fatal("duplicate dispatch")
	}
	closeNode(t, m, id)
}
func TestTCPHalfCloseKeepsReadAlive(t *testing.T) {
	ln, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	defer ln.Close()
	server := make(chan error, 1)
	go func() {
		c, e := ln.Accept()
		if e != nil {
			server <- e
			return
		}
		defer c.Close()
		c.SetDeadline(time.Now().Add(time.Second))
		data, e := io.ReadAll(c)
		if e == nil && string(data) != "hello" {
			e = fmt.Errorf("unexpected %q", data)
		}
		if e == nil {
			_, e = c.Write([]byte("reply"))
		}
		server <- e
	}()
	client, e := net.DialTimeout("tcp", ln.Addr().String(), time.Second)
	if e != nil {
		t.Fatal(e)
	}
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	sid := addStream(m, id, client)
	if _, n, rc := m.streamIO(sid, []byte("hello"), 5, 1000, true, false); rc != ok || n != 5 {
		t.Fatal(n, rc)
	}
	eventually(t, func() bool { s := m.getStream(sid); s.mu.Lock(); defer s.mu.Unlock(); return !s.writing })
	if _, _, rc := m.streamIO(sid, nil, 0, 1000, true, true); rc != ok {
		t.Fatal(rc)
	}
	b, n, rc := m.streamIO(sid, nil, 16, 1000, false, false)
	if rc != ok || string(b[:n]) != "reply" {
		t.Fatal(n, rc)
	}
	if e := <-server; e != nil {
		t.Fatal(e)
	}
	closeNode(t, m, id)
}

func TestNodeCancelWakesStartButKeepsEngine(t *testing.T) {
	gate := make(chan struct{})
	entered := make(chan struct{})
	f := &fakeEngine{start: func() error { close(entered); <-gate; return nil }}
	m := managerWith(f)
	id := addNode(t, m, "x")
	res := make(chan code, 1)
	go func() { res <- m.start(id, 60000) }()
	<-entered
	if m.nodeCancel(id) != ok {
		t.Fatal("cancel")
	}
	select {
	case c := <-res:
		if c != cancelled {
			t.Fatal(c)
		}
	case <-time.After(time.Second):
		t.Fatal("Start waiter not awakened")
	}
	if f.closes.Load() != 0 || m.nodeRelease(id) != busy {
		t.Fatal("Start owner freed")
	}
	close(gate)
	closeNode(t, m, id)
}

func TestHandleExhaustionFailsClosedWithoutReuse(t *testing.T) {
	m := managerWith(&fakeEngine{})
	m.next = ^uint64(0)
	if id, c := m.newNode(config{Directory: "x"}, nil); id != 0 || c != limit {
		t.Fatal(id, c)
	}
}

type failingCloseConn struct {
	stubbornConn
	failures atomic.Int32
}

func (c *failingCloseConn) Close() error {
	c.closes.Add(1)
	if c.failures.Add(-1) >= 0 {
		return errors.New("injected close failure")
	}
	return nil
}
func TestEngineCloseFailureRetainsQuotaAndOnlyExplicitRetry(t *testing.T) {
	var failed atomic.Bool
	a := &fakeEngine{close: func() error {
		if !failed.Swap(true) {
			return errors.New("injected engine close failure")
		}
		return nil
	}}
	b := &fakeEngine{}
	m := newManager(func(c config, _ stateStore) engine {
		if c.Directory == "A" {
			return a
		}
		return b
	})
	aid := addNode(t, m, "A")
	bid := addNode(t, m, "B")
	if m.start(aid, 1000) != ok || m.start(bid, 1000) != ok {
		t.Fatal("start")
	}
	if c := m.nodeClose(aid, 1000); c != ioError {
		t.Fatal(c)
	}
	if m.nodeRelease(aid) != busy {
		t.Fatal("close failure released node/context")
	}
	for i := 0; i < 6; i++ {
		addNode(t, m, fmt.Sprint(i))
	}
	if _, c := m.newNode(config{Directory: "ninth"}, nil); c != limit {
		t.Fatal("failed close freed quota")
	}
	if m.nodeCancel(aid) != ok || a.closes.Load() != 1 {
		t.Fatal("cancel silently retried Close")
	}
	s, c := m.control(bid, 1000, false)
	if c != ok || s.State != "Running" || b.closes.Load() != 0 {
		t.Fatal("other node disturbed", s, c)
	}
	if m.nodeClose(aid, 1000) != ok || m.nodeRelease(aid) != ok || a.closes.Load() != 2 {
		t.Fatal("exact engine retry failed")
	}
	if id, c := m.newNode(config{Directory: "replacement"}, nil); c != ok || id <= bid {
		t.Fatal(id, c)
	}
	closeNode(t, m, bid)
}
func TestStreamCloseFailureRetainsOwnerAndExplicitRetry(t *testing.T) {
	f := &fakeEngine{}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	c := &failingCloseConn{}
	c.failures.Store(1)
	sid := addStream(m, id, c)
	if rc := m.streamClose(sid, 1000); rc != ioError {
		t.Fatal(rc)
	}
	if m.streamRelease(sid) != busy || m.nodeRelease(id) != busy {
		t.Fatal("failed conn close freed owner")
	}
	if m.streamCancel(sid) != ok || c.closes.Load() != 1 {
		t.Fatal("cancel retried failed Close")
	}
	if _, _, rc := m.streamIO(sid, []byte("unsafe"), 6, 10, true, false); rc != cancelled || c.writes.Load() != 0 {
		t.Fatal("failed close allowed input")
	}
	if rc := m.nodeClose(id, 1000); rc != ok {
		t.Fatal(rc)
	}
	if c.closes.Load() != 2 || f.closes.Load() != 1 {
		t.Fatal("exact stream not retried before engine close")
	}
	if m.nodeRelease(id) != busy {
		t.Fatal("owned stream silently released")
	}
	if m.streamRelease(sid) != ok || m.nodeRelease(id) != ok {
		t.Fatal("final release")
	}
}
func TestNodeCloseStreamFailureDoesNotCloseEngineOrRelease(t *testing.T) {
	f := &fakeEngine{}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	c := &failingCloseConn{}
	c.failures.Store(1)
	sid := addStream(m, id, c)
	if rc := m.nodeClose(id, 1000); rc != ioError {
		t.Fatal(rc)
	}
	if f.closes.Load() != 0 || m.nodeRelease(id) != busy || m.streamRelease(sid) != busy {
		t.Fatal("engine/context released despite failed child close")
	}
	if c.closes.Load() != 1 {
		t.Fatal("implicit retry in one node Close")
	}
	if rc := m.nodeClose(id, 1000); rc != ok {
		t.Fatal(rc)
	}
	if c.closes.Load() != 2 || f.closes.Load() != 1 {
		t.Fatal("retry count")
	}
	closeNode(t, m, id)
}
func TestLateDialCloseFailureRetainedUntilExplicitNodeRetry(t *testing.T) {
	gate := make(chan struct{})
	c := &failingCloseConn{}
	c.failures.Store(1)
	f := &fakeEngine{dial: func(context.Context, string) (net.Conn, error) { <-gate; return c, nil }}
	m := managerWith(f)
	id := addNode(t, m, "x")
	if m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	if sid, rc := m.dial(id, "100.64.0.1:22", 5); rc != timedOut || sid != 0 {
		t.Fatal(sid, rc)
	}
	close(gate)
	eventually(t, func() bool {
		m.mu.Lock()
		defer m.mu.Unlock()
		if len(m.streams) != 1 {
			return false
		}
		for _, s := range m.streams {
			s.mu.Lock()
			a := s.closeAttempt
			s.mu.Unlock()
			if a == nil {
				return false
			}
			select {
			case <-a.done:
				return a.err != nil
			default:
				return false
			}
		}
		return false
	})
	if c.closes.Load() != 1 {
		t.Fatal("orphan silently retried")
	}
	m.nodeCancel(id)
	n := m.getNode(id)
	n.mu.Lock()
	a := n.closeAttempt
	n.mu.Unlock()
	if rc := waitAttempt(a, 1000); rc != ioError {
		t.Fatal(rc)
	}
	if f.closes.Load() != 0 || m.nodeRelease(id) != busy {
		t.Fatal("failed orphan released owner")
	}
	if rc := m.nodeClose(id, 1000); rc != ok {
		t.Fatal(rc)
	}
	m.mu.Lock()
	count := len(m.streams)
	m.mu.Unlock()
	if count != 0 || c.closes.Load() != 2 || f.closes.Load() != 1 || m.nodeRelease(id) != ok {
		t.Fatal("orphan did not clean after exact retry", count)
	}
}

func TestCloseRetryStillWaitsOriginalIOBeforeRelease(t *testing.T) {
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, "x")
	c := &failingCloseConn{stubbornConn: stubbornConn{writeGate: make(chan struct{}), writeEntered: make(chan struct{})}}
	c.failures.Store(1)
	sid := addStream(m, id, c)
	result := make(chan code, 1)
	go func() { _, _, rc := m.streamIO(sid, []byte("once"), 4, 60000, true, false); result <- rc }()
	<-c.writeEntered
	if rc := m.streamClose(sid, 1000); rc != ioError {
		t.Fatal(rc)
	}
	if rc := <-result; rc != unknownWrite {
		t.Fatal(rc)
	}
	if m.streamRelease(sid) != busy {
		t.Fatal("failure freed original IO")
	}
	if rc := m.streamClose(sid, 5); rc != timedOut {
		t.Fatal("retry ignored original IO", rc)
	}
	if c.closes.Load() != 2 || m.streamRelease(sid) != busy {
		t.Fatal("retry ended before original IO")
	}
	close(c.writeGate)
	if m.streamClose(sid, 1000) != ok || m.streamRelease(sid) != ok || c.closes.Load() != 2 || c.writes.Load() != 1 {
		t.Fatal("late IO cleanup or replay")
	}
	closeNode(t, m, id)
}

type backgroundStore struct {
	readEntered, writeEntered, readGate, writeGate chan struct{}
	reads, writes                                  atomic.Int32
}

func (s *backgroundStore) Read(string) ([]byte, bool, error) {
	s.reads.Add(1)
	if s.readEntered != nil {
		close(s.readEntered)
	}
	if s.readGate != nil {
		<-s.readGate
	}
	return []byte("state"), true, nil
}
func (s *backgroundStore) Write(string, []byte, bool) error {
	s.writes.Add(1)
	if s.writeEntered != nil {
		close(s.writeEntered)
	}
	if s.writeGate != nil {
		<-s.writeGate
	}
	return nil
}
func TestStoreRetirementWaitsBackgroundReadWriteAndBlocksLateHostAccess(t *testing.T) {
	host := &backgroundStore{readEntered: make(chan struct{}), writeEntered: make(chan struct{}), readGate: make(chan struct{}), writeGate: make(chan struct{})}
	var oldEngineStore stateStore
	f := &fakeEngine{}
	m := newManager(func(_ config, s stateStore) engine { oldEngineStore = s; return f })
	id, c := m.newNode(config{Directory: "A"}, host)
	if c != ok || m.start(id, 1000) != ok {
		t.Fatal("start", c)
	}
	readResult := make(chan error, 1)
	writeResult := make(chan error, 1)
	// Simulate engine-owned background work which was not joined by Close and
	// which is absent from manager API inflight accounting.
	go func() { _, _, e := oldEngineStore.Read("read"); readResult <- e }()
	go func() { writeResult <- oldEngineStore.Write("write", []byte("value"), false) }()
	<-host.readEntered
	<-host.writeEntered
	if rc := m.nodeClose(id, 5); rc != timedOut || m.nodeRelease(id) != busy {
		t.Fatal("background callbacks released context", rc)
	}
	if f.closes.Load() != 1 {
		t.Fatal("test did not reach successful engine Close")
	}
	close(host.readGate)
	if e := <-readResult; e != nil {
		t.Fatal(e)
	}
	if rc := m.nodeClose(id, 5); rc != timedOut || m.nodeRelease(id) != busy {
		t.Fatal("remaining Write lease ignored", rc)
	}
	close(host.writeGate)
	if e := <-writeResult; e != nil {
		t.Fatal(e)
	}
	if m.nodeClose(id, 1000) != ok || m.nodeRelease(id) != ok || f.closes.Load() != 1 {
		t.Fatal("store retirement did not settle")
	}
	for i := 0; i < 10; i++ {
		if _, _, e := oldEngineStore.Read("late-read"); e == nil {
			t.Fatal("late read succeeded")
		}
		if e := oldEngineStore.Write("late-write", nil, true); e == nil {
			t.Fatal("late write succeeded")
		}
	}
	if host.reads.Load() != 1 || host.writes.Load() != 1 {
		t.Fatal("released host store touched", host.reads.Load(), host.writes.Load())
	}
}
func TestFailedCloseKeepsStoreGateUntilExactRetry(t *testing.T) {
	host := &backgroundStore{}
	var oldEngineStore stateStore
	var failed atomic.Bool
	f := &fakeEngine{close: func() error {
		if !failed.Swap(true) {
			return errors.New("injected close failure")
		}
		return nil
	}}
	m := newManager(func(_ config, s stateStore) engine { oldEngineStore = s; return f })
	id, c := m.newNode(config{Directory: "A"}, host)
	if c != ok || m.start(id, 1000) != ok {
		t.Fatal("start")
	}
	if m.nodeClose(id, 1000) != ioError || m.nodeRelease(id) != busy {
		t.Fatal("failed Close released context")
	}
	if _, _, e := oldEngineStore.Read("still-owned"); e != nil {
		t.Fatal("failed Close retired store early", e)
	}
	if e := oldEngineStore.Write("still-owned", []byte{}, false); e != nil {
		t.Fatal(e)
	}
	if m.nodeClose(id, 1000) != ok || m.nodeRelease(id) != ok || f.closes.Load() != 2 {
		t.Fatal("retry")
	}
	if _, _, e := oldEngineStore.Read("after-release"); e == nil {
		t.Fatal("late read")
	}
	if e := oldEngineStore.Write("after-release", nil, true); e == nil {
		t.Fatal("late write")
	}
	if host.reads.Load() != 1 || host.writes.Load() != 1 {
		t.Fatal("host access after release")
	}
}
func TestUnstartedNodeRetiresStoreWithoutEngineClose(t *testing.T) {
	host := &backgroundStore{}
	var oldEngineStore stateStore
	f := &fakeEngine{}
	m := newManager(func(_ config, s stateStore) engine { oldEngineStore = s; return f })
	id, c := m.newNode(config{Directory: "A"}, host)
	if c != ok {
		t.Fatal(c)
	}
	if m.nodeClose(id, 1000) != ok || m.nodeRelease(id) != ok || f.starts.Load() != 0 || f.closes.Load() != 0 {
		t.Fatal("unstarted retirement")
	}
	if _, _, e := oldEngineStore.Read("late"); e == nil {
		t.Fatal("late read")
	}
	if e := oldEngineStore.Write("late", []byte("x"), false); e == nil {
		t.Fatal("late write")
	}
	if host.reads.Load() != 0 || host.writes.Load() != 0 {
		t.Fatal("host touched after unstarted release")
	}
}
