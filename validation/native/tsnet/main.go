// This build/load probe never starts tsnet, joins a tailnet, or reads state.
package main

import "C"
import (
    "context"
    "net"
    "tailscale.com/tsnet"
)

type byteStreamDialer interface {
    Dial(context.Context, string, string) (net.Conn, error)
    Close() error
}

var _ byteStreamDialer = (*tsnet.Server)(nil)

//export hp_probe_abi_version
func hp_probe_abi_version() C.int { return 1 }

func main() {}
