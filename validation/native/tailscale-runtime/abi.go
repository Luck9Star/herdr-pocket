package main

/*
#include "hp_ts.h"
static inline int32_t store_read(hp_ts_store_callbacks *s, uint64_t c, const uint8_t *k, uint32_t n, uint8_t **v, uint32_t *l, uint32_t *f) {return s->read(c,k,n,v,l,f);}
static inline int32_t store_write(hp_ts_store_callbacks *s, uint64_t c, const uint8_t *k, uint32_t n, const uint8_t *v, uint32_t l, uint32_t d) {return s->write(c,k,n,v,l,d);}
static inline void store_release(hp_ts_store_callbacks *s, uint64_t c, uint8_t *v, uint32_t l) {s->release(c,v,l);}
static inline int valid_store(hp_ts_store_callbacks *s) {return s && s->read && s->write && s->release;}
*/
import "C"
import (
	"encoding/json"
	"errors"
	"unicode/utf8"
	"unsafe"
)

var runtimeManager = newManager(makeTSEngine)

type cStore struct {
	callbacks C.hp_ts_store_callbacks
	context   C.uint64_t
}

func bytesPointer(data []byte) *C.uint8_t {
	if len(data) == 0 {
		return nil
	}
	return (*C.uint8_t)(unsafe.Pointer(&data[0]))
}
func (s *cStore) Read(key string) ([]byte, bool, error) {
	if len(key) > 1024 {
		return nil, false, errors.New("state key rejected")
	}
	k := []byte(key)
	var ptr *C.uint8_t
	var length, found C.uint32_t
	rc := C.store_read(&s.callbacks, s.context, bytesPointer(k), C.uint32_t(len(k)), &ptr, &length, &found)
	if ptr != nil {
		defer C.store_release(&s.callbacks, s.context, ptr, length)
	}
	if rc != 0 || length > 262144 || found > 1 || (length > 0 && ptr == nil) || (found == 0 && (length != 0 || ptr != nil)) {
		return nil, false, errors.New("state read failed")
	}
	if found == 0 {
		return nil, false, nil
	}
	if length == 0 {
		return []byte{}, true, nil
	}
	return C.GoBytes(unsafe.Pointer(ptr), C.int(length)), true, nil
}
func (s *cStore) Write(key string, data []byte, deleted bool) error {
	if len(key) > 1024 || len(data) > 262144 {
		return errors.New("state value rejected")
	}
	k := []byte(key)
	var d C.uint32_t
	if deleted {
		d = 1
	}
	if C.store_write(&s.callbacks, s.context, bytesPointer(k), C.uint32_t(len(k)), bytesPointer(data), C.uint32_t(len(data)), d) != 0 {
		return errors.New("state write failed")
	}
	return nil
}
func input(ptr *C.uint8_t, n C.uint32_t, max uint32) ([]byte, bool) {
	if uint32(n) > max || (n > 0 && ptr == nil) {
		return nil, false
	}
	return C.GoBytes(unsafe.Pointer(ptr), C.int(n)), true
}
func output(data []byte, ptr *C.uint8_t, capacity C.uint32_t, length *C.uint32_t) code {
	if length == nil || (capacity > 0 && ptr == nil) {
		return invalid
	}
	*length = C.uint32_t(len(data))
	if uint64(len(data)) > uint64(capacity) {
		return bufferSmall
	}
	if len(data) > 0 {
		copy(unsafe.Slice((*byte)(unsafe.Pointer(ptr)), int(capacity)), data)
	}
	return ok
}

//export hp_ts_abi_version
func hp_ts_abi_version() C.uint32_t { return 1 }

//export hp_ts_node_new
func hp_ts_node_new(data *C.uint8_t, length C.uint32_t, callbacks *C.hp_ts_store_callbacks, ctx C.uint64_t, out *C.uint64_t) C.int32_t {
	if out == nil {
		return C.int32_t(invalid)
	}
	*out = 0
	b, yes := input(data, length, 16384)
	if !yes || C.valid_store(callbacks) == 0 {
		return C.int32_t(invalid)
	}
	c, err := parseConfig(b)
	if err != nil {
		return C.int32_t(invalid)
	}
	id, rc := runtimeManager.newNode(c, &cStore{*callbacks, ctx})
	*out = C.uint64_t(id)
	return C.int32_t(rc)
}

//export hp_ts_node_start
func hp_ts_node_start(id C.uint64_t, ms C.uint32_t) C.int32_t {
	return C.int32_t(runtimeManager.start(uint64(id), uint32(ms)))
}

//export hp_ts_node_status
func hp_ts_node_status(id C.uint64_t, ms C.uint32_t, data *C.uint8_t, capacity C.uint32_t, length *C.uint32_t) C.int32_t {
	if length == nil || capacity > 8192 || (capacity > 0 && data == nil) {
		return C.int32_t(invalid)
	}
	*length = 0
	s, rc := runtimeManager.control(uint64(id), uint32(ms), false)
	if rc != ok {
		return C.int32_t(rc)
	}
	b, _ := json.Marshal(s)
	if len(b) > 8192 {
		return C.int32_t(ioError)
	}
	return C.int32_t(output(b, data, capacity, length))
}

//export hp_ts_node_begin_login
func hp_ts_node_begin_login(id C.uint64_t, ms C.uint32_t) C.int32_t {
	_, rc := runtimeManager.control(uint64(id), uint32(ms), true)
	return C.int32_t(rc)
}

//export hp_ts_node_dial
func hp_ts_node_dial(id C.uint64_t, address *C.uint8_t, length C.uint32_t, ms C.uint32_t, out *C.uint64_t) C.int32_t {
	if out == nil {
		return C.int32_t(invalid)
	}
	*out = 0
	b, yes := input(address, length, 4096)
	if !yes || !utf8.Valid(b) {
		return C.int32_t(invalid)
	}
	sid, rc := runtimeManager.dial(uint64(id), string(b), uint32(ms))
	*out = C.uint64_t(sid)
	return C.int32_t(rc)
}

//export hp_ts_stream_read
func hp_ts_stream_read(id C.uint64_t, data *C.uint8_t, capacity C.uint32_t, ms C.uint32_t, length *C.uint32_t) C.int32_t {
	if length == nil || capacity > maxIO || (capacity > 0 && data == nil) {
		return C.int32_t(invalid)
	}
	*length = 0
	b, n, rc := runtimeManager.streamIO(uint64(id), nil, int(capacity), uint32(ms), false, false)
	if n > 0 {
		copy(unsafe.Slice((*byte)(unsafe.Pointer(data)), int(capacity)), b[:n])
		*length = C.uint32_t(n)
	}
	return C.int32_t(rc)
}

//export hp_ts_stream_write
func hp_ts_stream_write(id C.uint64_t, data *C.uint8_t, length C.uint32_t, ms C.uint32_t, written *C.uint32_t) C.int32_t {
	if written == nil {
		return C.int32_t(invalid)
	}
	*written = 0
	b, yes := input(data, length, maxIO)
	if !yes {
		return C.int32_t(invalid)
	}
	_, n, rc := runtimeManager.streamIO(uint64(id), b, len(b), uint32(ms), true, false)
	*written = C.uint32_t(n)
	return C.int32_t(rc)
}

//export hp_ts_stream_shutdown_write
func hp_ts_stream_shutdown_write(id C.uint64_t, ms C.uint32_t) C.int32_t {
	_, _, rc := runtimeManager.streamIO(uint64(id), nil, 0, uint32(ms), true, true)
	return C.int32_t(rc)
}

//export hp_ts_stream_cancel
func hp_ts_stream_cancel(id C.uint64_t) C.int32_t {
	return C.int32_t(runtimeManager.streamCancel(uint64(id)))
}

//export hp_ts_stream_close
func hp_ts_stream_close(id C.uint64_t, ms C.uint32_t) C.int32_t {
	return C.int32_t(runtimeManager.streamClose(uint64(id), uint32(ms)))
}

//export hp_ts_stream_release
func hp_ts_stream_release(id C.uint64_t) C.int32_t {
	return C.int32_t(runtimeManager.streamRelease(uint64(id)))
}

//export hp_ts_node_cancel
func hp_ts_node_cancel(id C.uint64_t) C.int32_t {
	return C.int32_t(runtimeManager.nodeCancel(uint64(id)))
}

//export hp_ts_node_close
func hp_ts_node_close(id C.uint64_t, ms C.uint32_t) C.int32_t {
	return C.int32_t(runtimeManager.nodeClose(uint64(id), uint32(ms)))
}

//export hp_ts_node_release
func hp_ts_node_release(id C.uint64_t) C.int32_t {
	return C.int32_t(runtimeManager.nodeRelease(uint64(id)))
}
func main() {}
