package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
)

func goodRawInterfaces() []rawInterface {
	return []rawInterface{{
		Name: "test0", Index: 7, MTU: 1500,
		Flags: net.FlagUp | net.FlagBroadcast | net.FlagMulticast,
		Addrs: []net.Addr{&net.IPNet{IP: net.IPv4(192, 0, 2, 10), Mask: net.CIDRMask(24, 32)}},
	}}
}

func goodGoNet() ([]rawInterface, error) { return goodRawInterfaces(), nil }

func failingGetifaddrs() ([]rawInterface, error) { return nil, errors.New("getifaddrs failed") }

// stubNetmonPaths swaps enumerators and registers the getter: swapping paths
// means the test wants the alternate getter to be the one under test.
func stubNetmonPaths(t *testing.T, goFn, cgoFn func() ([]rawInterface, error)) {
	t.Helper()
	registerNetmonGetterForTest()
	oldGo, oldCgo := goNetPath, getifaddrsPath
	goNetPath, getifaddrsPath = goFn, cgoFn
	netmonDiag.reset()
	t.Cleanup(func() {
		goNetPath, getifaddrsPath = oldGo, oldCgo
		netmonDiag.reset()
	})
}

// enableNetmonForTest opts a node directory into diagnose persistence exactly
// like the device probe does: by creating the marker file. The production
// marker-gated persist path is exercised unchanged.
func enableNetmonForTest(t *testing.T, dir string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, netmonDiagnoseOptInFileName), nil, 0o600); err != nil {
		t.Fatal(err)
	}
}

func readDiagnoseFile(t *testing.T, dir string) netmonDiagnose {
	t.Helper()
	payload, err := os.ReadFile(filepath.Join(dir, netmonDiagnoseFileName))
	if err != nil {
		t.Fatalf("read diagnose: %v", err)
	}
	var d netmonDiagnose
	if err := json.Unmarshal(payload, &d); err != nil {
		t.Fatalf("parse diagnose %q: %v", payload, err)
	}
	return d
}

// Production registration is Android-only; desktop hosts keep stock netmon.
// Declared first: no earlier test may have opted into registration.
func TestEnsureNetmonGetterNoOpNonAndroid(t *testing.T) {
	if runtime.GOOS == "android" {
		t.Skip("Android registers the real getter")
	}
	if got := netmonGetterRegistrations.Load(); got != 0 {
		t.Fatalf("registrations=%d before any test opt-in", got)
	}
	ensureNetmonGetter()
	if got := netmonGetterRegistrations.Load(); got != 0 {
		t.Fatalf("ensureNetmonGetter registered on %s", runtime.GOOS)
	}
}

// AltAddrs=nil would make netmon.Interface.Addrs() fall back to netlink,
// re-introducing the Android failure; the converter must repair nil slices.
func TestNetmonAltAddrsNeverNil(t *testing.T) {
	out := toNetmonInterfaces([]rawInterface{{Name: "x0", Index: 1, Flags: net.FlagUp}})
	if len(out) != 1 || out[0].AltAddrs == nil {
		t.Fatal("nil AltAddrs survived conversion")
	}
	addrs, err := out[0].Addrs()
	if err != nil || len(addrs) != 0 {
		t.Fatalf("Addrs() = %v, %v; want empty, nil", addrs, err)
	}
	kept := []net.Addr{&net.IPAddr{IP: net.IPv4(192, 0, 2, 1)}}
	out = toNetmonInterfaces([]rawInterface{{Name: "x1", Index: 2, Addrs: kept}})
	if len(out[0].AltAddrs) != 1 {
		t.Fatal("existing addresses dropped")
	}
}

func TestNetmonGetterFallback(t *testing.T) {
	for _, tc := range []struct {
		name   string
		goErr  error
		goKind string
	}{
		{"permission", fmt.Errorf("netlink: %w", os.ErrPermission), "permission"},
		{"empty", errNetmonEmpty, "empty"},
		{"other", errors.New("socket failed"), "other"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			stubNetmonPaths(t, func() ([]rawInterface, error) { return nil, tc.goErr }, goodGoNet)
			d := diagnoseNetmon()
			if !d.StateBuilt || d.StateErrClass != "" {
				t.Fatalf("stateBuilt=%v stateErrClass=%q", d.StateBuilt, d.StateErrClass)
			}
			if d.Selected != netmonPathGetifaddrs {
				t.Fatalf("selected=%q", d.Selected)
			}
			if d.Paths[0].Path != netmonPathGoNet || d.Paths[0].ErrClass != tc.goKind || d.Paths[0].OK {
				t.Fatalf("goNet diag %+v", d.Paths[0])
			}
			if d.Paths[1].Path != netmonPathGetifaddrs || d.Paths[1].ErrClass != "none" ||
				d.Paths[1].Interfaces != 1 || d.Paths[1].Addresses != 1 {
				t.Fatalf("getifaddrs diag %+v", d.Paths[1])
			}
			if d.GetterCalls != 1 {
				t.Fatalf("getterCalls=%d", d.GetterCalls)
			}
		})
	}
}

func TestDiagnoseGetterFailureHidesRawError(t *testing.T) {
	const secret = "raw-secret-netlink-detail"
	stubNetmonPaths(t,
		func() ([]rawInterface, error) { return nil, errors.New("goNet " + secret) },
		func() ([]rawInterface, error) { return nil, errors.New("getifaddrs " + secret) })
	d := diagnoseNetmon()
	if d.StateBuilt || d.StateErrClass == "" {
		t.Fatalf("stateBuilt=%v stateErrClass=%q", d.StateBuilt, d.StateErrClass)
	}
	if d.Selected != "none" {
		t.Fatalf("selected=%q", d.Selected)
	}
	payload, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(payload), secret) {
		t.Fatalf("raw error text leaked: %s", payload)
	}
	for _, p := range d.Paths {
		if p.OK || p.ErrClass != "other" {
			t.Fatalf("path %+v", p)
		}
	}
}

func TestNodeNewWritesNoDiagnoseUntilStatus(t *testing.T) {
	stubNetmonPaths(t, goodGoNet, failingGetifaddrs)
	dir := t.TempDir()
	enableNetmonForTest(t, dir)
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, dir)
	defer closeNode(t, m, id)
	// node_new writes nothing, even with the opt-in marker present.
	if _, err := os.Stat(filepath.Join(dir, netmonDiagnoseFileName)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("initial diagnose file exists: %v", err)
	}
	if got := netmonDiag.calls.Load(); got != 0 {
		t.Fatalf("node_new enumerated interfaces: calls=%d", got)
	}
	if _, c := m.control(id, 1000, false); c != ok {
		t.Fatalf("status=%v", c)
	}
	info, err := os.Stat(filepath.Join(dir, netmonDiagnoseFileName))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", info.Mode().Perm())
	}
	d := readDiagnoseFile(t, dir)
	if d.Event != "netmon_diagnose" || !d.GetterRegistered || !d.StateBuilt {
		t.Fatalf("first measured diagnose %+v", d)
	}
}

// Without the opt-in marker a node directory gains no files and no extra
// interface enumeration happens; with it, status writes measured state.
func TestNetmonDiagnoseOptInGate(t *testing.T) {
	stubNetmonPaths(t, goodGoNet, failingGetifaddrs)
	dir := t.TempDir()
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, dir) // no marker: newNode persist must be a no-op
	defer closeNode(t, m, id)
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("node dir grew files without opt-in: %v", entries)
	}
	if _, c := m.control(id, 1000, false); c != ok { // Stopped
		t.Fatalf("status=%v", c)
	}
	if got := netmonDiag.calls.Load(); got != 0 {
		t.Fatalf("unmarked status enumerated interfaces: calls=%d", got)
	}
	if _, err := os.Stat(filepath.Join(dir, netmonDiagnoseFileName)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("diagnose file without opt-in: %v", err)
	}
	enableNetmonForTest(t, dir)
	if _, c := m.control(id, 1000, false); c != ok {
		t.Fatalf("status=%v", c)
	}
	d := readDiagnoseFile(t, dir)
	if !d.StateBuilt || d.GetterCalls != 1 || d.Selected != netmonPathGoNet {
		t.Fatalf("measured diagnose after opt-in %+v", d)
	}
}

// Node A measures first; node B's directory stays empty after node_new and
// only B's own status refresh may create B's file with fresh measurements.
// Counters are process-wide by design: B's file legitimately accumulates.
func TestNetmonDiagnosePerNodeIsolation(t *testing.T) {
	stubNetmonPaths(t, goodGoNet, failingGetifaddrs)
	m := managerWith(&fakeEngine{})
	dirA, dirB := t.TempDir(), t.TempDir()
	enableNetmonForTest(t, dirA)
	enableNetmonForTest(t, dirB)
	idA := addNode(t, m, dirA)
	defer closeNode(t, m, idA)
	if c := m.start(idA, 1000); c != ok {
		t.Fatalf("start A=%v", c)
	}
	if _, c := m.control(idA, 1000, false); c != ok {
		t.Fatalf("status A=%v", c)
	}
	a := readDiagnoseFile(t, dirA)
	if a.GetterCalls == 0 || !a.StateBuilt {
		t.Fatalf("node A not measured %+v", a)
	}
	idB := addNode(t, m, dirB)
	defer closeNode(t, m, idB)
	// After A already measured, node_new still leaves B's directory empty.
	if _, err := os.Stat(filepath.Join(dirB, netmonDiagnoseFileName)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("node B initial file exists: %v", err)
	}
	if c := m.start(idB, 1000); c != ok {
		t.Fatalf("start B=%v", c)
	}
	if _, c := m.control(idB, 1000, false); c != ok {
		t.Fatalf("status B=%v", c)
	}
	b2 := readDiagnoseFile(t, dirB)
	if b2.GetterCalls == 0 || !b2.StateBuilt || b2.Selected != netmonPathGoNet {
		t.Fatalf("node B not measured %+v", b2)
	}
	// Counters are process-wide: B's measured file accumulates on top of A's.
	if b2.GetterCalls <= a.GetterCalls {
		t.Fatalf("expected process-level accumulation A=%d B=%d", a.GetterCalls, b2.GetterCalls)
	}
}

// A failing engine.Start must not be misreported as a netmon failure: the
// status refresh still records a successfully built state.
func TestStatusRefreshesDiagnoseAfterStartFailure(t *testing.T) {
	stubNetmonPaths(t, goodGoNet, failingGetifaddrs)
	dir := t.TempDir()
	enableNetmonForTest(t, dir)
	m := managerWith(&fakeEngine{start: func() error { return errors.New("engine start exploded") }})
	id := addNode(t, m, dir)
	defer closeNode(t, m, id)
	if c := m.start(id, 1000); c != ioError {
		t.Fatalf("start=%v", c)
	}
	_, _ = m.control(id, 1000, false) // hp_ts_node_status path
	d := readDiagnoseFile(t, dir)
	if !d.StateBuilt || d.StateErrClass != "" {
		t.Fatalf("stateBuilt=%v stateErrClass=%q", d.StateBuilt, d.StateErrClass)
	}
	if d.Selected != netmonPathGoNet || d.GetterCalls == 0 {
		t.Fatalf("selected=%q calls=%d", d.Selected, d.GetterCalls)
	}
	p := d.Paths[0]
	if p.Path != netmonPathGoNet || !p.OK || p.ErrClass != "none" || p.Interfaces != 1 || p.Addresses != 1 {
		t.Fatalf("goNet diag %+v", p)
	}
	if d.Paths[1].ErrClass != "" {
		t.Fatalf("getifaddrs should not have run: %+v", d.Paths[1])
	}
}

func TestDiagnoseWriteFailureDoesNotAffectStart(t *testing.T) {
	old := netmonPersistDiagnose
	netmonPersistDiagnose = func(string) error { return errors.New("disk full") }
	t.Cleanup(func() { netmonPersistDiagnose = old })
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, t.TempDir()) // newNode stays ok despite write failure
	defer closeNode(t, m, id)
	if c := m.start(id, 1000); c != ok {
		t.Fatalf("start=%v with failing diagnose writer", c)
	}
	if _, c := m.control(id, 1000, false); c != ok {
		t.Fatalf("status=%v with failing diagnose writer", c)
	}
}

func TestConcurrentStatusDiagnoseFileNotTorn(t *testing.T) {
	stubNetmonPaths(t, goodGoNet, failingGetifaddrs)
	dir := t.TempDir()
	enableNetmonForTest(t, dir)
	m := managerWith(&fakeEngine{})
	id := addNode(t, m, dir)
	defer closeNode(t, m, id)
	if c := m.start(id, 1000); c != ok {
		t.Fatalf("start=%v", c)
	}
	path := filepath.Join(dir, netmonDiagnoseFileName)
	stop := make(chan struct{})
	errCh := make(chan error, 1)
	report := func(err error) {
		select {
		case errCh <- err:
		default:
		}
	}
	var readers sync.WaitGroup
	readers.Add(1)
	go func() {
		defer readers.Done()
		for {
			select {
			case <-stop:
				return
			default:
			}
			payload, err := os.ReadFile(path)
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			if err != nil {
				report(err)
				return
			}
			var d netmonDiagnose
			if err := json.Unmarshal(payload, &d); err != nil {
				report(fmt.Errorf("torn file %q: %w", payload, err))
				return
			}
		}
	}()
	var writers sync.WaitGroup
	for range 8 {
		writers.Add(1)
		go func() {
			defer writers.Done()
			for range 20 {
				_, _ = m.control(id, 1000, false)
			}
		}()
	}
	writers.Wait()
	close(stop)
	readers.Wait()
	select {
	case err := <-errCh:
		t.Fatal(err)
	default:
	}
	if d := readDiagnoseFile(t, dir); !d.StateBuilt || d.GetterCalls == 0 {
		t.Fatalf("final diagnose %+v", d)
	}
}

func TestNetmonConcurrentRegistrationAndCalls(t *testing.T) {
	stubNetmonPaths(t, goodGoNet, failingGetifaddrs)
	var wg sync.WaitGroup
	for range 16 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if d := diagnoseNetmon(); !d.StateBuilt {
				t.Error("state not built")
			}
		}()
	}
	wg.Wait()
	if got := netmonGetterRegistrations.Load(); got != 1 {
		t.Fatalf("registrations=%d, want exactly 1", got)
	}
	if got := netmonDiag.calls.Load(); got != 16 {
		t.Fatalf("getterCalls=%d, want 16", got)
	}
}

// Real-host smoke: prints one diagnose JSON sample and checks the schema.
func TestNetmonDiagnoseHost(t *testing.T) {
	registerNetmonGetterForTest()
	netmonDiag.reset()
	d := diagnoseNetmon()
	payload, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("netmon diagnose: %s", payload)
	var keys map[string]any
	if err := json.Unmarshal(payload, &keys); err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"event", "getterRegistered", "getterCalls", "paths", "selected",
		"stateBuilt", "stateErrClass", "haveV4", "haveV6", "anyUp"} {
		if _, ok := keys[k]; !ok {
			t.Fatalf("missing key %q in %s", k, payload)
		}
	}
	if !d.GetterRegistered {
		t.Fatal("getter not registered")
	}
}

func TestNetmonGetifaddrsHost(t *testing.T) {
	raws, err := getifaddrsInterfaces()
	if err != nil {
		t.Fatalf("getifaddrs: %v", err)
	}
	total := 0
	for _, r := range raws {
		if r.Name == "" || r.Index <= 0 {
			t.Fatalf("bad interface %+v", r)
		}
		total += len(r.Addrs)
	}
	if total == 0 {
		t.Fatal("no addresses enumerated")
	}
	for i, iface := range toNetmonInterfaces(raws) {
		if iface.AltAddrs == nil {
			t.Fatalf("interface %d has nil AltAddrs", i)
		}
	}
}
