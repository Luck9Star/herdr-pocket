//go:build !cgo || (!android && !darwin && !linux)

package main

import "errors"

func getifaddrsInterfaces() ([]rawInterface, error) {
	return nil, errors.New("getifaddrs unsupported on this platform")
}
