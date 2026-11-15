// One-shot read of the pinned upstream netmon state; no test override or network write.
package main

import (
	"encoding/json"
	"os"

	"tailscale.com/net/netmon"
)

func main() {
	state := netmon.NewStatic().InterfaceState()
	if state == nil {
		os.Exit(1)
	}
	if json.NewEncoder(os.Stdout).Encode(map[string]bool{
		"haveV4":         state.HaveV4,
		"haveV6":         state.HaveV6,
		"anyInterfaceUp": state.AnyInterfaceUp(),
	}) != nil {
		os.Exit(1)
	}
}
