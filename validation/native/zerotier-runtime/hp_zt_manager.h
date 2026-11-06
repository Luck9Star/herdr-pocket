/* App-owned control plane for the pinned, patched libzt candidate.
 * This API never creates an identity or opens a socket. All control of this
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
enum hp_zt_managed_result {
    HP_ZT_MANAGED_OK = 0, HP_ZT_MANAGED_ARGUMENT = 1,
    HP_ZT_MANAGED_STALE = 2, HP_ZT_MANAGED_BUSY = 3,
    HP_ZT_MANAGED_TIMEOUT = 4, HP_ZT_MANAGED_NATIVE = 5,
    HP_ZT_MANAGED_CAPACITY = 6, HP_ZT_MANAGED_NOT_ONLINE = 7,
    HP_ZT_MANAGED_IDENTITY = 8, HP_ZT_MANAGED_CLOSING = 9
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
 * Must not be used on the callback thread. This manager currently has no socket
 * API; stream admissions/drain must be added before a socket backend is exposed. */
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
#ifdef __cplusplus
}
#endif
#endif
