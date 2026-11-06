/* Synthetic ABI v1 fixture. No sockets, nodes, DNS, identities or EasyTier code.
 * Deliberately includes rejection, partial progress, blocking I/O, unknown writes,
 * delayed open/return, half-close, and a first-close failure. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

typedef struct {
    uint64_t id, node;
    int closed, half_closed, close_failed;
    char mode[32];
    uint8_t bytes[65536];
    size_t length;
} Slot;
static Slot slots[256];
static uint64_t next_id = 1;
static int open_calls, write_calls, close_calls, close_successes, active_calls;
static int release_open, release_write;
static size_t accepted_bytes;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int failure(int code, char *err, size_t n) {
    if (err && n) snprintf(err, n, "synthetic native fixture failure");
    return code;
}
static Slot *find(uint64_t id) {
    if (!id || id >= next_id || id > 256) return NULL;
    return &slots[id - 1];
}
static void reset_nodes(void);
static int node_metric(int metric);
static void control_node(int operation);
void fixture_reset(void) {
    reset_nodes();
    pthread_mutex_lock(&mutex);
    memset(slots, 0, sizeof(slots)); next_id = 1;
    open_calls = write_calls = close_calls = close_successes = active_calls = release_open = release_write = 0; accepted_bytes = 0;
    pthread_mutex_unlock(&mutex);
}
void fixture_control(int operation) {
    pthread_mutex_lock(&mutex);
    control_node(operation);
    if (operation == 1) release_open = 1;
    if (operation == 2) release_write = 1;
    pthread_cond_broadcast(&changed); pthread_mutex_unlock(&mutex);
}
int fixture_metric(int metric) {
    pthread_mutex_lock(&mutex); int value = 0;
    if (metric == 0) { for (uint64_t i = 1; i < next_id; ++i) if (!slots[i-1].closed) ++value; }
    else if (metric == 1) value = open_calls;
    else if (metric == 2) value = write_calls;
    else if (metric == 3) value = close_calls;
    else if (metric == 4) value = close_successes;
    else if (metric == 5) value = active_calls;
    else if (metric == 6) value = (int)accepted_bytes;
    else value = node_metric(metric);
    pthread_mutex_unlock(&mutex); return value;
}
int heeler_et_stream_connect(const char *key, const char *network, const char *host,
                            uint16_t port, uint32_t timeout_ms, uint64_t *out, char *err, size_t errlen) {
    if (!out || !key || !network || !host || !port || !timeout_ms) return failure(-1, err, errlen);
    *out = 0;
    pthread_mutex_lock(&mutex); ++open_calls; ++active_calls;
    while (strcmp(host, "late") == 0 && !release_open) pthread_cond_wait(&changed, &mutex);
    --active_calls;
    if (strcmp(host, "reject") == 0) { pthread_mutex_unlock(&mutex); return failure(-3, err, errlen); }
    if (next_id > 256) { pthread_mutex_unlock(&mutex); return failure(-9, err, errlen); }
    Slot *slot = &slots[next_id - 1]; slot->id = next_id++; snprintf(slot->mode, sizeof(slot->mode), "%s", host);
    if (strcmp(host, "read-block") != 0 && strcmp(host, "slow-write") != 0 && strcmp(host, "unknown") != 0) {
        slot->length = (size_t)snprintf((char *)slot->bytes, sizeof(slot->bytes), "%s|%s", key, network);
    }
    *out = slot->id; pthread_mutex_unlock(&mutex); return 0;
}
int heeler_et_stream_read(uint64_t id, uint8_t *buf, size_t len, uint32_t timeout_ms, char *err, size_t errlen) {
    if (!buf || !len || len > 65536) return failure(-6, err, errlen);
    struct timespec until; clock_gettime(CLOCK_REALTIME, &until);
    until.tv_sec += timeout_ms / 1000; until.tv_nsec += (long)(timeout_ms % 1000) * 1000000;
    if (until.tv_nsec >= 1000000000) { until.tv_sec++; until.tv_nsec -= 1000000000; }
    pthread_mutex_lock(&mutex); Slot *slot = find(id);
    if (!slot || slot->closed) { pthread_mutex_unlock(&mutex); return failure(-6, err, errlen); }
    ++active_calls;
    while (!slot->closed && !slot->half_closed && slot->length == 0) {
        if (pthread_cond_timedwait(&changed, &mutex, &until) == ETIMEDOUT) {
            --active_calls; pthread_mutex_unlock(&mutex); return failure(-2, err, errlen);
        }
    }
    --active_calls;
    if (slot->closed) { pthread_mutex_unlock(&mutex); return failure(-7, err, errlen); }
    size_t count = slot->length < len ? slot->length : len;
    memcpy(buf, slot->bytes, count); memmove(slot->bytes, slot->bytes + count, slot->length - count); slot->length -= count;
    pthread_mutex_unlock(&mutex); return (int)count;
}
int heeler_et_stream_write(uint64_t id, const uint8_t *buf, size_t len, uint32_t timeout_ms, char *err, size_t errlen) {
    if (!buf || !len || len > 65536 || !timeout_ms) return failure(-6, err, errlen);
    pthread_mutex_lock(&mutex); Slot *slot = find(id);
    if (!slot || slot->closed || slot->half_closed) { pthread_mutex_unlock(&mutex); return failure(-8, err, errlen); }
    ++write_calls; ++active_calls;
    while (strcmp(slot->mode, "slow-write") == 0 && !release_write) pthread_cond_wait(&changed, &mutex);
    --active_calls; slot = find(id);
    if (!slot || slot->closed) { pthread_mutex_unlock(&mutex); return failure(-8, err, errlen); }
    int unknown = strcmp(slot->mode, "unknown") == 0;
    size_t count = unknown ? 1 : (strcmp(slot->mode, "short") == 0 && len > 2 ? 2 : len);
    if (count > sizeof(slot->bytes) - slot->length) { pthread_mutex_unlock(&mutex); return failure(-8, err, errlen); }
    memcpy(slot->bytes + slot->length, buf, count); slot->length += count; accepted_bytes += count;
    pthread_cond_broadcast(&changed); pthread_mutex_unlock(&mutex);
    return unknown ? failure(-8, err, errlen) : (int)count;
}
int heeler_et_stream_shutdown_write(uint64_t id, uint32_t timeout_ms, char *err, size_t errlen) {
    (void)timeout_ms;
    pthread_mutex_lock(&mutex); Slot *slot = find(id);
    if (!slot || slot->closed) { pthread_mutex_unlock(&mutex); return failure(-6, err, errlen); }
    slot->half_closed = 1; pthread_cond_broadcast(&changed); pthread_mutex_unlock(&mutex); return 0;
}
int heeler_et_stream_close(uint64_t id, char *err, size_t errlen) {
    pthread_mutex_lock(&mutex); ++close_calls; Slot *slot = find(id);
    if (!slot || slot->closed) { pthread_mutex_unlock(&mutex); return failure(-6, err, errlen); }
    if (strcmp(slot->mode, "close-fail") == 0 && !slot->close_failed) {
        slot->close_failed = 1; pthread_mutex_unlock(&mutex); return failure(-10, err, errlen);
    }
    slot->closed = 1; ++close_successes; pthread_cond_broadcast(&changed); pthread_mutex_unlock(&mutex); return 0;
}

/* Managed-node symbols are synthetic as well. No engine or network exists. */
typedef struct { uint64_t id; int stopped, stop_failed; char config[256]; } Node;
static Node nodes[64];
static uint64_t next_node = 1;
static int node_starts, node_stops, node_statuses, release_start, stop_order_violations;
static Node *node_find(uint64_t id) {
    if (!id || id >= next_node || id > 64 || nodes[id-1].stopped) return NULL;
    return &nodes[id-1];
}
int heeler_et_node_start(const char *config, uint32_t timeout_ms, uint64_t *out, char *err, size_t errlen) {
    if (!config || !out || !timeout_ms) return failure(-1, err, errlen);
    *out = 0;
    pthread_mutex_lock(&mutex); ++node_starts; ++active_calls;
    if (next_node > 64) { --active_calls; pthread_mutex_unlock(&mutex); return failure(-9, err, errlen); }
    Node *node = &nodes[next_node-1]; node->id = next_node++;
    snprintf(node->config, sizeof(node->config), "%s", config); *out = node->id;
    while (strstr(config, "late-start") && !release_start) pthread_cond_wait(&changed, &mutex);
    --active_calls;
    int code = strstr(config, "start-fail") ? -2 : 0;
    pthread_mutex_unlock(&mutex); return code ? failure(code, err, errlen) : 0;
}
int heeler_et_node_status(uint64_t id, uint32_t *state, char *err, size_t errlen) {
    pthread_mutex_lock(&mutex); ++node_statuses; Node *node = node_find(id);
    if (!node || !state) { pthread_mutex_unlock(&mutex); return failure(-6, err, errlen); }
    *state = 1; pthread_mutex_unlock(&mutex); return 0;
}
int heeler_et_node_stop(uint64_t id, uint32_t timeout_ms, char *err, size_t errlen) {
    (void)timeout_ms;
    pthread_mutex_lock(&mutex); ++node_stops; Node *node = node_find(id);
    if (!node) { pthread_mutex_unlock(&mutex); return failure(-6, err, errlen); }
    for (uint64_t i = 1; i < next_id; ++i) {
        if (!slots[i-1].closed && slots[i-1].node == id) {
            ++stop_order_violations; pthread_mutex_unlock(&mutex); return failure(-10, err, errlen);
        }
    }
    if (strstr(node->config, "stop-fail") && !node->stop_failed) {
        node->stop_failed = 1; pthread_mutex_unlock(&mutex); return failure(-2, err, errlen);
    }
    node->stopped = 1; pthread_mutex_unlock(&mutex); return 0;
}
int heeler_et_node_stream_connect(uint64_t id, const char *network, const char *host, uint16_t port,
                                 uint32_t timeout_ms, uint64_t *out, char *err, size_t errlen) {
    pthread_mutex_lock(&mutex); Node *node = node_find(id);
    int valid = node && network && strstr(node->config, network);
    pthread_mutex_unlock(&mutex);
    if (!valid) return failure(-4, err, errlen);
    char key[64]; snprintf(key, sizeof(key), "managed-%llu", (unsigned long long)id);
    int code = heeler_et_stream_connect(key, network, host, port, timeout_ms, out, err, errlen);
    if (code == 0) { pthread_mutex_lock(&mutex); find(*out)->node = id; pthread_mutex_unlock(&mutex); }
    return code;
}

static void reset_nodes(void) {
    pthread_mutex_lock(&mutex);
    memset(nodes, 0, sizeof(nodes)); next_node = 1;
    node_starts = node_stops = node_statuses = release_start = stop_order_violations = 0;
    pthread_mutex_unlock(&mutex);
}
static int node_metric(int metric) {
    if (metric == 7) { int count = 0; for (uint64_t i=1; i<next_node; ++i) if (!nodes[i-1].stopped) ++count; return count; }
    if (metric == 8) return node_starts;
    if (metric == 9) return node_stops;
    if (metric == 10) return node_statuses;
    if (metric == 11) return stop_order_violations;
    return 0;
}
static void control_node(int operation) { if (operation == 3) release_start = 1; }
