/* herdr-pocket candidate: no node/network is started by identity functions.
 * Upstream libzt, ZeroTierOne and Heeler patch attribution is retained separately.
 */
#ifndef HERDR_POCKET_ZT_H
#define HERDR_POCKET_ZT_H
#include <stddef.h>
#include <stdint.h>
#if defined(_WIN32)
#define HP_ZT_API __declspec(dllexport)
#else
#define HP_ZT_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
#define HP_ZT_ABI_VERSION 1u
#define HP_ZT_IDENTITY_BYTES 270u
#define HP_ZT_IDENTITY_WORK_BYTES 384u
/* Secret output is exactly 270 canonical ASCII bytes, without a NUL terminator.
 * No secret is serialized as JSON, logged, or exported to a GUI. The native
 * vault must atomically persist it before admitting a node start. */
enum hp_zt_result {
    HP_ZT_OK = 0, HP_ZT_INVALID_ARGUMENT = 1, HP_ZT_BUFFER_TOO_SMALL = 2,
    HP_ZT_IDENTITY_INVALID = 3, HP_ZT_UNAVAILABLE = 4, HP_ZT_TIMEOUT = 5,
    HP_ZT_BUSY = 6
};
HP_ZT_API uint32_t hp_zt_abi_version(void);
HP_ZT_API int hp_zt_identity_create(uint8_t *output, size_t capacity, size_t *output_length, uint64_t *node_id);
HP_ZT_API int hp_zt_identity_validate(const uint8_t *identity, size_t length, uint64_t *node_id);
/* Process-global control-plane safety primitives, not profile handles. Caller
 * must hold the original device-node owner/epoch and drain its stream/API leases.
 * Timeout does not release any owner or callback context. 1..60000ms only.
 * Callback-thread stop/free returns BUSY after requesting retirement.
 * Ordinary stop leaves the process-global lwIP stack alive for a later start.
 * Free permanently closes initialization; lwIP's internal tcpip thread is not
 * claimed to be joined (the fixed lwIP has no such shutdown API). */
HP_ZT_API int hp_zt_node_stop(uint32_t timeout_ms);
HP_ZT_API int hp_zt_node_free(uint32_t timeout_ms);
/* 1 only when both service and callback workers have left and the service has
 * been destroyed. This does not substitute for the caller's stream/API drain. */
HP_ZT_API int hp_zt_node_quiescent(void);
#ifdef __cplusplus
}
#endif
#endif
