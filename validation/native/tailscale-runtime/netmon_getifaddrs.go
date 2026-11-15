//go:build cgo && (android || darwin || linux)

package main

/*
#include <sys/types.h>
#include <sys/socket.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <errno.h>

static int hp_getifaddrs(struct ifaddrs **out) {
	int rc = getifaddrs(out);
	return rc == 0 ? 0 : errno;
}
*/
import "C"

import (
	"errors"
	"net"
	"os"
	"unsafe"
)

// getifaddrsInterfaces enumerates real interfaces through libc, which works
// under Android app UIDs where netlink is denied. MTU stays 0 (not needed by
// netmon state building) to avoid extra ioctls.
func getifaddrsInterfaces() ([]rawInterface, error) {
	var head *C.struct_ifaddrs
	if errno := C.hp_getifaddrs(&head); errno != 0 {
		if errno == C.EPERM || errno == C.EACCES {
			return nil, os.ErrPermission
		}
		return nil, errors.New("getifaddrs failed")
	}
	if head == nil {
		return nil, errNetmonEmpty
	}
	defer C.freeifaddrs(head)
	var raws []rawInterface
	slots := map[string]int{}
	for ifa := head; ifa != nil; ifa = ifa.ifa_next {
		if ifa.ifa_addr == nil {
			continue
		}
		var ip net.IP
		var mask net.IPMask
		switch ifa.ifa_addr.sa_family {
		case C.AF_INET:
			addr := (*C.struct_sockaddr_in)(unsafe.Pointer(ifa.ifa_addr))
			ip = net.IP(C.GoBytes(unsafe.Pointer(&addr.sin_addr), 4))
			if ifa.ifa_netmask != nil {
				nm := (*C.struct_sockaddr_in)(unsafe.Pointer(ifa.ifa_netmask))
				mask = net.IPMask(C.GoBytes(unsafe.Pointer(&nm.sin_addr), 4))
			}
		case C.AF_INET6:
			addr := (*C.struct_sockaddr_in6)(unsafe.Pointer(ifa.ifa_addr))
			ip = net.IP(C.GoBytes(unsafe.Pointer(&addr.sin6_addr), 16))
			if ifa.ifa_netmask != nil {
				nm := (*C.struct_sockaddr_in6)(unsafe.Pointer(ifa.ifa_netmask))
				mask = net.IPMask(C.GoBytes(unsafe.Pointer(&nm.sin6_addr), 16))
			}
		default:
			continue
		}
		name := C.GoString(ifa.ifa_name)
		slot, ok := slots[name]
		if !ok {
			slot = len(raws)
			slots[name] = slot
			raws = append(raws, rawInterface{
				Name:  name,
				Index: int(C.if_nametoindex(ifa.ifa_name)),
				Flags: convertIfFlags(C.uint(ifa.ifa_flags)),
			})
		}
		if mask != nil {
			raws[slot].Addrs = append(raws[slot].Addrs, &net.IPNet{IP: ip, Mask: mask})
		} else {
			raws[slot].Addrs = append(raws[slot].Addrs, &net.IPAddr{IP: ip})
		}
	}
	if len(raws) == 0 {
		return nil, errNetmonEmpty
	}
	return raws, nil
}

func convertIfFlags(f C.uint) net.Flags {
	var out net.Flags
	if f&C.IFF_UP != 0 {
		out |= net.FlagUp
	}
	if f&C.IFF_BROADCAST != 0 {
		out |= net.FlagBroadcast
	}
	if f&C.IFF_LOOPBACK != 0 {
		out |= net.FlagLoopback
	}
	if f&C.IFF_POINTOPOINT != 0 {
		out |= net.FlagPointToPoint
	}
	if f&C.IFF_MULTICAST != 0 {
		out |= net.FlagMulticast
	}
	return out
}
