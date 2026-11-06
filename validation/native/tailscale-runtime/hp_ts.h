#ifndef HP_TS_H
#define HP_TS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* v1: all byte buffers are borrowed for the call. No NUL requirement.
 * Handles are monotonically allocated, never reused. No file descriptors.
 * timeout_ms must be 1..60000; IO len/cap <=65536. No automatic retry.
 */
enum hp_ts_result { HP_TS_OK=0, HP_TS_INVALID=1, HP_TS_NOT_FOUND=2,
 HP_TS_BUSY=3, HP_TS_LIMIT=4, HP_TS_TIMEOUT=5, HP_TS_CANCELLED=6,
 HP_TS_NOT_RUNNING=7, HP_TS_IO=8, HP_TS_UNKNOWN_WRITE=9, HP_TS_BUFFER=10, HP_TS_UNSUPPORTED=11 };
/* read: found=0 means absent; found=1,len=0 means present empty.
 * On success release is called exactly once for any non-NULL data pointer,
 * after copying. Callbacks must be thread safe; errors fail closed.
 * write: delete_value=1 deletes; delete_value=0,len=0 stores an empty value.
 * Keys are passed unchanged (<=1024 bytes, including empty); values
 * <=262144 bytes; oversize fails closed. Status JSON max8192/auth URL max4096.
 * Full arbitrary StateStore keys are passed unchanged. No Go disk fallback.
 */
typedef int32_t (*hp_ts_store_read_fn)(uint64_t context, const uint8_t *key,
 uint32_t key_len, uint8_t **data, uint32_t *len, uint32_t *found);
typedef int32_t (*hp_ts_store_write_fn)(uint64_t context, const uint8_t *key,
 uint32_t key_len, const uint8_t *data, uint32_t len, uint32_t delete_value);
typedef void (*hp_ts_store_release_fn)(uint64_t context, uint8_t *data, uint32_t len);
typedef struct hp_ts_store_callbacks {
 hp_ts_store_read_fn read;
 hp_ts_store_write_fn write;
 hp_ts_store_release_fn release;
} hp_ts_store_callbacks;
uint32_t hp_ts_abi_version(void);
/* config JSON: {"directory":"unique app-private path","hostname":"...",
 * "control_url":"https://controlplane.tailscale.com"}. Unknown fields rejected.
 * No auth key/environment credentials. new reserves quota, does not start.
 * new error with node=0 guarantees no asynchronous work/callback use.
 */
int32_t hp_ts_node_new(uint8_t *config, uint32_t len,
 hp_ts_store_callbacks *store, uint64_t context, uint64_t *node);
int32_t hp_ts_node_start(uint64_t node, uint32_t timeout_ms);
/* JSON {"state":"Starting|NeedsLogin|NeedsMachineAuth|Running|Closing|Stopped",
 * "auth_url":""}. Auth URL only exposed after explicit begin_login.
 * Required byte length is always returned; BUFFER makes no partial copy.
 */
int32_t hp_ts_node_status(uint64_t node, uint32_t timeout_ms,
 uint8_t *data, uint32_t cap, uint32_t *len);
int32_t hp_ts_node_begin_login(uint64_t node, uint32_t timeout_ms);
/* TCP only, explicit address host:port (no implicit proxy/local fallback). */
int32_t hp_ts_node_dial(uint64_t node, uint8_t *address, uint32_t len,
 uint32_t timeout_ms, uint64_t *stream);
int32_t hp_ts_stream_read(uint64_t stream, uint8_t *data, uint32_t cap,
 uint32_t timeout_ms, uint32_t *len);
int32_t hp_ts_stream_write(uint64_t stream, uint8_t *data, uint32_t len,
 uint32_t timeout_ms, uint32_t *written);
/* cancel initiates close without waiting. close is idempotent, may TIMEOUT.
 * Close returning IO retains the object, callback context and quota. Only
 * explicit close retries that exact object; cancel never retries failed Close.
 * Failed orphan Dial cleanup is retained for explicit node_close retry.
 * Start timeout/cancel requests node close; Close never races engine Start.
 * A write interrupted after dispatch is UNKNOWN_WRITE, never replayed.
 */
/* TIMEOUT read is returned only after underlying Read completes with zero
 * bytes. Caller wait expiring with unfinished Read retires the stream and
 * returns CANCELLED (never a retryable read timeout).
 * Half-close uses CloseWrite when supported; unsupported never full-closes.
 */
int32_t hp_ts_stream_shutdown_write(uint64_t stream, uint32_t timeout_ms);
int32_t hp_ts_stream_cancel(uint64_t stream);
int32_t hp_ts_stream_close(uint64_t stream, uint32_t timeout_ms);
int32_t hp_ts_node_cancel(uint64_t node);
int32_t hp_ts_node_close(uint64_t node, uint32_t timeout_ms);
/* release succeeds only after real close AND all in-flight work completes.
 * Until successful node_release, callbacks/context MUST remain alive, even
 * after timeout/cancel. Each node gates every StateStore callback; successful
 * close waits in-flight callback leases, then rejects late callback attempts
 * without calling the host. Close failure leaves the gate/context retained.
 * Quotas retained through late cleanup. Stream release
 * likewise waits real close+IO completion. Max 8 nodes / 32 streams globally.
 */
int32_t hp_ts_stream_release(uint64_t stream);
int32_t hp_ts_node_release(uint64_t node);
#ifdef __cplusplus
}
#endif
#endif
