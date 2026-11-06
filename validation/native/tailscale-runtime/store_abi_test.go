//go:build hp_ts_test

package main

import (
	"bytes"
	"testing"
)

func TestNativeStoreMissingEmptyValueAndDelete(t *testing.T) {
	s := bridgeStore(0)
	v, found, e := s.Read("")
	if e != nil || found || v != nil {
		t.Fatal(v, found, e)
	}
	s = bridgeStore(1)
	v, found, e = s.Read("_machinekey")
	if e != nil || !found || v == nil || len(v) != 0 {
		t.Fatal(v, found, e)
	}
	s = bridgeStore(2)
	v, found, e = s.Read("profiles/\x00/key")
	released, _, _, _ := bridgeCounts()
	if e != nil || !found || string(v) != "abc" || released != 1 {
		t.Fatal(v, found, e, released)
	}
	if e = s.Write("", []byte{}, false); e != nil {
		t.Fatal(e)
	}
	_, n, d, l := bridgeCounts()
	if n != 1 || d || l != 0 {
		t.Fatal("empty write became delete")
	}
	if e = s.Write("_machinekey", nil, true); e != nil {
		t.Fatal(e)
	}
	_, n, d, l = bridgeCounts()
	if n != 2 || !d || l != 0 {
		t.Fatal("delete not distinct")
	}
}
func TestNativeStoreErrorReleasesMalformedHostAllocation(t *testing.T) {
	for _, mode := range []int{3, 4, 5} {
		s := bridgeStore(mode)
		if _, _, e := s.Read("key"); e == nil {
			t.Fatal(mode)
		}
		released, _, _, _ := bridgeCounts()
		if released != 1 {
			t.Fatalf("mode %d allocation leaked", mode)
		}
	}
}
func TestNativeStoreLimitsAndIOFailClosed(t *testing.T) {
	s := bridgeStore(0)
	if _, _, e := s.Read(string(bytes.Repeat([]byte{'k'}, 1025))); e == nil {
		t.Fatal("oversize key")
	}
	if e := s.Write("key", make([]byte, 262145), false); e == nil {
		t.Fatal("oversize value")
	}
	s = bridgeStore(6)
	if e := s.Write("key", []byte("x"), false); e == nil {
		t.Fatal("host IO error treated as success")
	}
}
func TestTSStoreMissingAndEmptyRemainDistinct(t *testing.T) {
	s := tsStore{store: &memoryStore{values: map[string][]byte{}}}
	if _, e := s.ReadState("key"); e == nil {
		t.Fatal("missing")
	}
	if e := s.WriteState("key", []byte{}); e != nil {
		t.Fatal(e)
	}
	v, e := s.ReadState("key")
	if e != nil || v == nil || len(v) != 0 {
		t.Fatal(v, e)
	}
	if e := s.WriteState("key", nil); e != nil {
		t.Fatal(e)
	}
	if _, e := s.ReadState("key"); e == nil {
		t.Fatal("delete")
	}
}
