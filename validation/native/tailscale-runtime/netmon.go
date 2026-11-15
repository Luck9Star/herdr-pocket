package main

import (
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"sync/atomic"

	"tailscale.com/net/netmon"
)

// Android app UIDs cannot use netlink (golang/go#40569), so Go's
// net.Interfaces fails inside tsnet's netmon.New. Registering an alternate
// getter that falls back to libc getifaddrs keeps tsnet start working. The
// diagnose payload is read-only: it records classes and counts, never raw
// error text, interface names, or IP addresses.
const netmonDiagnoseFileName = "netmon-diagnose.json"

// Diagnostics are strictly opt-in: without this marker in the node directory
// no diagnose file is written and no extra interface enumeration happens.
const netmonDiagnoseOptInFileName = "netmon-diagnose.optin"

const (
	netmonPathGoNet      = "goNet"
	netmonPathGetifaddrs = "getifaddrs"
)

var errNetmonEmpty = errors.New("no network interfaces")

type rawInterface struct {
	Name  string
	Index int
	MTU   int
	Flags net.Flags
	Addrs []net.Addr
}

type netmonPathDiag struct {
	Path       string `json:"path"`
	OK         bool   `json:"ok"`
	ErrClass   string `json:"errClass"`
	Interfaces int    `json:"interfaces"`
	Addresses  int    `json:"addresses"`
}

type netmonDiagnose struct {
	Event            string           `json:"event"`
	GetterRegistered bool             `json:"getterRegistered"`
	GetterCalls      uint64           `json:"getterCalls"`
	Paths            []netmonPathDiag `json:"paths"`
	Selected         string           `json:"selected"`
	StateBuilt       bool             `json:"stateBuilt"`
	StateErrClass    string           `json:"stateErrClass"`
	HaveV4           bool             `json:"haveV4"`
	HaveV6           bool             `json:"haveV6"`
	AnyUp            bool             `json:"anyUp"`
}

type netmonDiagnostics struct {
	mu       sync.Mutex
	paths    [2]netmonPathDiag
	selected string
	calls    atomic.Uint64
}

func emptyNetmonPaths() [2]netmonPathDiag {
	return [2]netmonPathDiag{{Path: netmonPathGoNet}, {Path: netmonPathGetifaddrs}}
}

// Measurements are process-wide, not per-node: multiple nodes share the
// getter and counters, so each node's diagnose file is that node's own
// snapshot of the same accumulating process-level numbers (expected).
var netmonDiag = netmonDiagnostics{paths: emptyNetmonPaths(), selected: "none"}

func (d *netmonDiagnostics) record(slot int, raws []rawInterface, err error) {
	p := netmonPathDiag{OK: err == nil, ErrClass: netmonErrClass(err), Interfaces: len(raws)}
	for i := range raws {
		p.Addresses += len(raws[i].Addrs)
	}
	d.mu.Lock()
	p.Path = d.paths[slot].Path
	d.paths[slot] = p
	d.mu.Unlock()
}

func (d *netmonDiagnostics) selectPath(s string) {
	d.mu.Lock()
	d.selected = s
	d.mu.Unlock()
}

func (d *netmonDiagnostics) snapshot() ([2]netmonPathDiag, string) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.paths, d.selected
}

// reset clears measurements only; registration once-state is kept so tests
// can prove registration happens exactly once per process.
func (d *netmonDiagnostics) reset() {
	d.mu.Lock()
	d.paths = emptyNetmonPaths()
	d.selected = "none"
	d.mu.Unlock()
	d.calls.Store(0)
}

// errClass is "" only for a path that never executed; "none" means success.
func netmonErrClass(err error) string {
	switch {
	case err == nil:
		return "none"
	case errors.Is(err, errNetmonEmpty):
		return "empty"
	case errors.Is(err, os.ErrPermission):
		return "permission"
	default:
		return "other"
	}
}

// Test injection points; production keeps the real enumerators.
var (
	goNetPath      = goNetInterfaces
	getifaddrsPath = getifaddrsInterfaces
)

var (
	netmonGetterOnce          sync.Once
	netmonGetterRegistrations atomic.Uint64
)

// Production registers the alternate getter only on Android: desktop hosts
// keep stock netmon behavior (already-validated Linux/macOS paths). Tests
// call registerNetmonGetterForTest directly on any platform.
func ensureNetmonGetter() {
	if runtime.GOOS != "android" {
		return
	}
	netmonGetterOnce.Do(func() {
		netmon.RegisterInterfaceGetter(netmonInterfaceGetter)
		netmonGetterRegistrations.Add(1)
	})
}

// Test-only registration for non-Android platforms (Linux CI getifaddrs).
func registerNetmonGetterForTest() {
	netmonGetterOnce.Do(func() {
		netmon.RegisterInterfaceGetter(netmonInterfaceGetter)
		netmonGetterRegistrations.Add(1)
	})
}

func netmonInterfaceGetter() ([]netmon.Interface, error) {
	netmonDiag.calls.Add(1)
	raws, goErr := goNetPath()
	netmonDiag.record(0, raws, goErr)
	if goErr == nil {
		netmonDiag.selectPath(netmonPathGoNet)
		return toNetmonInterfaces(raws), nil
	}
	raws, cgoErr := getifaddrsPath()
	netmonDiag.record(1, raws, cgoErr)
	if cgoErr == nil {
		netmonDiag.selectPath(netmonPathGetifaddrs)
		return toNetmonInterfaces(raws), nil
	}
	netmonDiag.selectPath("none")
	if !errors.Is(goErr, errNetmonEmpty) {
		return nil, goErr
	}
	return nil, cgoErr
}

func goNetInterfaces() ([]rawInterface, error) {
	ifs, err := net.Interfaces()
	if err != nil {
		return nil, err
	}
	if len(ifs) == 0 {
		return nil, errNetmonEmpty
	}
	raws := make([]rawInterface, 0, len(ifs))
	for i := range ifs {
		addrs, err := ifs[i].Addrs()
		if err != nil {
			return nil, err
		}
		raws = append(raws, rawInterface{
			Name: ifs[i].Name, Index: ifs[i].Index, MTU: ifs[i].MTU,
			Flags: ifs[i].Flags, Addrs: addrs,
		})
	}
	return raws, nil
}

// AltAddrs must stay non-nil: netmon.Interface.Addrs() falls back to
// net.Interface.Addrs() (netlink on Android) when AltAddrs is nil.
func toNetmonInterfaces(raws []rawInterface) []netmon.Interface {
	out := make([]netmon.Interface, 0, len(raws))
	for i := range raws {
		r := &raws[i]
		addrs := r.Addrs
		if addrs == nil {
			addrs = []net.Addr{}
		}
		out = append(out, netmon.Interface{
			Interface: &net.Interface{Name: r.Name, Index: r.Index, MTU: r.MTU, Flags: r.Flags},
			AltAddrs:  addrs,
		})
	}
	return out
}

// diagnoseNetmon measures fresh state through the registered getter. It never
// opens connections or starts tsnet.
func diagnoseNetmon() netmonDiagnose {
	ensureNetmonGetter()
	st := netmon.NewStatic().InterfaceState()
	var stateErr error
	if st == nil {
		// NewStatic swallows the build error; reproduce it read-only.
		_, stateErr = netmon.GetInterfaceList()
	}
	paths, selected := netmonDiag.snapshot()
	d := netmonDiagnose{
		Event:            "netmon_diagnose",
		GetterRegistered: netmonGetterRegistrations.Load() > 0,
		GetterCalls:      netmonDiag.calls.Load(),
		Paths:            paths[:],
		Selected:         selected,
		StateBuilt:       st != nil,
	}
	if st != nil {
		d.HaveV4, d.HaveV6, d.AnyUp = st.HaveV4, st.HaveV6, st.AnyInterfaceUp()
	} else {
		d.StateErrClass = netmonErrClass(stateErr)
	}
	return d
}

// Best-effort persistence; failures never alter node lifecycle return codes.
var netmonPersistDiagnose = persistNetmonDiagnose

func persistNetmonDiagnose(dir string) error {
	if dir == "" {
		return nil
	}
	// Opt-in marker required: without it write nothing and, critically, do
	// not even enumerate interfaces (normal nodes see zero extra work).
	if _, err := os.Stat(filepath.Join(dir, netmonDiagnoseOptInFileName)); err != nil {
		return nil
	}
	payload, err := json.Marshal(diagnoseNetmon())
	if err != nil {
		return err
	}
	return writeNetmonFileAtomic(filepath.Join(dir, netmonDiagnoseFileName), payload)
}

func writeNetmonFileAtomic(path string, payload []byte) error {
	tmp, err := os.CreateTemp(filepath.Dir(path), ".netmon-diagnose-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name) // no-op once renamed
	if _, err = tmp.Write(payload); err != nil {
		_ = tmp.Close()
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	// CreateTemp already uses 0600; rename keeps replacement atomic.
	return os.Rename(name, path)
}
