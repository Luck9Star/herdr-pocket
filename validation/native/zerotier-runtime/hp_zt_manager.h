/* App-owned control plane for the pinned, patched libzt candidate.
 * This API never creates an identity. All control and sockets of this
 * libzt instance must go through this manager. Do not mix raw node APIs.
 * Calls are synchronous native worker calls: timeout bounds manager admission
 * and native stop; upstream init/join/status cannot be preempted. A late return
 * is reported as timeout and retains ownership. Never free borrowed identity
 * storage or release a vault lease before the ORIGINAL call has returned. */
#ifndef HERDR_POCKET_ZT_MANAGER_H
#define HERDR_POCKET_ZT_MANAGER_H
#include "hp_zt.h"
#ifdef __cplusplus
extern "C" {
#endif
#define HP_ZT_MANAGER_ABI_VERSION 1u
#define HP_ZT_MAX_NETWORK_LEASES 32u
#define HP_ZT_MAX_STREAMS 32u
#define HP_ZT_MAX_IO_BYTES 65536u
#define HP_ZT_STREAM_ABI_VERSION 1u
HP_ZT_API uint32_t hp_zt_stream_abi_version(void);
enum hp_zt_managed_result {
    HP_ZT_MANAGED_OK = 0, HP_ZT_MANAGED_ARGUMENT = 1,
    HP_ZT_MANAGED_STALE = 2, HP_ZT_MANAGED_BUSY = 3,
    HP_ZT_MANAGED_TIMEOUT = 4, HP_ZT_MANAGED_NATIVE = 5,
    HP_ZT_MANAGED_CAPACITY = 6, HP_ZT_MANAGED_NOT_ONLINE = 7,
    HP_ZT_MANAGED_IDENTITY = 8, HP_ZT_MANAGED_CLOSING = 9,
    HP_ZT_MANAGED_CANCELLED = 10, HP_ZT_MANAGED_UNKNOWN_WRITE = 11,
    HP_ZT_MANAGED_UNSUPPORTED = 12, HP_ZT_MANAGED_ROUTE = 13
};
enum hp_zt_device_phase {
    HP_ZT_DEVICE_INITIALIZED = 1, HP_ZT_DEVICE_STARTED = 2,
    HP_ZT_DEVICE_CLOSING = 3, HP_ZT_DEVICE_STOPPED = 4,
    HP_ZT_DEVICE_FAULTED = 5
};
enum hp_zt_network_phase {
    HP_ZT_NETWORK_REQUESTING = 1,
    /* Config accepted is NOT proof of tap/link/address/route/socket readiness. */
    HP_ZT_NETWORK_CONFIGURED = 2,
    HP_ZT_NETWORK_DENIED = 3, HP_ZT_NETWORK_NOT_FOUND = 4,
    HP_ZT_NETWORK_PORT_ERROR = 5, HP_ZT_NETWORK_CLIENT_OLD = 6,
    HP_ZT_NETWORK_AUTH_REQUIRED = 7, HP_ZT_NETWORK_CLOSING = 8,
    HP_ZT_NETWORK_UNKNOWN = 9
};
HP_ZT_API uint32_t hp_zt_manager_abi_version(void);
/* Caller must already own the durable device-vault runtime lease. The identity
 * is borrowed only for this call; never pass it through GUI IPC. out_owner can
 * be NONZERO ON ERROR: retain the vault and explicitly stop/release that owner.
 * The owner is monotonic, process-global, non-reusable and not a GUI token.
 * No filesystem fallback, environment identity or implicit key generation. */
HP_ZT_API int hp_zt_device_new(const uint8_t *identity, size_t length,
    uint32_t timeout_ms, uint64_t *out_owner);
HP_ZT_API int hp_zt_device_start(uint64_t owner, uint32_t timeout_ms);
HP_ZT_API int hp_zt_device_status(uint64_t owner, uint32_t timeout_ms,
    uint32_t *phase, uint32_t *online, uint64_t *public_node_id);
/* Explicit DEVICE-WIDE maintenance: retires ALL network leases. Single-profile
 * disconnect must use network_leave instead. Timeout never releases ownership.
 * Must not be used on the callback thread. It first fences and drains every
 * stream's original native call and fd before stopping the stack. */
HP_ZT_API int hp_zt_device_stop(uint64_t owner, uint32_t timeout_ms);
/* Release only after exact owner stop + native quiescence, never NODE_DOWN.
 * Returns STALE for an already released/foreign owner; no arbitrary idempotent
 * success. Host must retain its successful release result for vault retirement. */
HP_ZT_API int hp_zt_device_release(uint64_t owner, uint32_t timeout_ms);
/* Each successful join allocates a distinct lease, even for the same network.
 * Same-network leases share one join. out_lease may be nonzero on a failed native
 * join: explicit leave or device-wide stop must retire that exact admission. */
HP_ZT_API int hp_zt_network_join(uint64_t owner, uint64_t network_id,
    uint32_t timeout_ms, uint64_t *out_lease);
HP_ZT_API int hp_zt_network_status(uint64_t owner, uint64_t lease,
    uint32_t timeout_ms, uint32_t *phase, uint32_t *online);
/* Last lease leaves the network. Other networks and the device vault survive.
 * Stop/release remains an explicit device action after all consumers agree. */
HP_ZT_API int hp_zt_network_leave(uint64_t owner, uint64_t lease, uint32_t timeout_ms);
/* Pure-memory reservation, before any FFI socket call. ip is a numeric network
 * byte-order IPv4(4 bytes)/IPv6(16 bytes), never a hostname or a system route.
 * All handles are monotonic/non-reusable. 32 GLOBAL slots include pending open,
 * failed close, cancelled and late calls until proven retirement. */
HP_ZT_API int hp_zt_stream_new(uint64_t owner, uint64_t lease,
    const uint8_t *ip, uint32_t ip_len, uint16_t port, uint64_t *out_stream);
/* One connect attempt only. The host has the handle before dispatch, so cancel
 * can fence an in-flight open. All buffers remain borrowed until ORIGINAL FFI
 * returns; a host wait expiring does not prove it returned. */
HP_ZT_API int hp_zt_stream_open(uint64_t owner, uint64_t lease, uint64_t stream, uint32_t timeout_ms);
/* One operation per direction. OK/len=0 is EOF. Read TIMEOUT is retryable only
 * after original nonblocking recv returns with zero bytes. Dispatching a write
 * then cancellation/deadline/uncertain error is UNKNOWN_WRITE; never replay.
 * Half-close retires writes only and retains reads. cap/len is 1..65536. */
HP_ZT_API int hp_zt_stream_read(uint64_t owner, uint64_t lease, uint64_t stream,
    uint8_t *data, uint32_t cap, uint32_t timeout_ms, uint32_t *len);
HP_ZT_API int hp_zt_stream_write(uint64_t owner, uint64_t lease, uint64_t stream,
    const uint8_t *data, uint32_t len, uint32_t timeout_ms, uint32_t *written);
HP_ZT_API int hp_zt_stream_shutdown_write(uint64_t owner, uint64_t lease, uint64_t stream, uint32_t timeout_ms);
HP_ZT_API int hp_zt_stream_cancel(uint64_t owner, uint64_t lease, uint64_t stream);
HP_ZT_API int hp_zt_stream_close(uint64_t owner, uint64_t lease, uint64_t stream, uint32_t timeout_ms);
HP_ZT_API int hp_zt_stream_release(uint64_t owner, uint64_t lease, uint64_t stream);
/* Successful network_leave/device_stop close affected streams. Exact closed
 * records remain, including quota, until explicit stream_release. close of an
 * existing closed record is OK even after its network lease left; only release
 * removes it. Repeated/foreign release is STALE, never arbitrary success.
 * device_release requires all stream records released. Failures retain ownership.
 * Never call raw libzt socket APIs or unload the DSO while an owner is held. */
#ifdef __cplusplus
}
#endif
#endif
