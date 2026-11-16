/* Test-only ABI shim for the Android Tailscale node probe.
 *
 * It dlopens the very same libhp_tailscale.so the product loads and drives
 * the plain C ABI (hp_ts_node_new -> hp_ts_node_status) with an in-memory
 * store, so the Go side is exercised without any Java StateStore callback
 * and without the Rust/JNI bridge in the path.
 *
 * Purpose: decide whether the netmon getter can return at all on Android.
 * hp_ts_node_status persists the diagnose snapshot before the not-started
 * branch returns, so a marker-present node directory yields a readable
 * netmon-diagnose.json even though no engine was ever started.
 *
 * Runs in its own instrumentation process: if the getter itself aborts, this
 * process dies and the main probe still records the bounded result.
 *
 * Never used by the product; probe-only build artifact.
 */
#include <dlfcn.h>
#include <jni.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>


/* The pinned header from the native-source checkout, passed via -I at build
 * time. __typeof__ keeps every function pointer type identical to the real
 * ABI instead of hand-copying signatures. */
#include "hp_ts.h"

typedef __typeof__(&hp_ts_abi_version) abi_version_fn;
typedef __typeof__(&hp_ts_node_new) node_new_fn;
typedef __typeof__(&hp_ts_node_status) node_status_fn;
typedef __typeof__(&hp_ts_node_close) node_close_fn;
typedef __typeof__(&hp_ts_node_release) node_release_fn;

/* In-memory store: every key is absent, writes are discarded. The Go side
 * must cope with a missing state key, which is exactly the pre-login case. */
static int32_t shim_read(uint64_t context, const uint8_t *key,
                         uint32_t key_len, uint8_t **data, uint32_t *len,
                         uint32_t *found) {
    (void)context;
    (void)key;
    (void)key_len;
    if (data) *data = NULL;
    if (len) *len = 0;
    if (found) *found = 0;
    return 0;
}

static int32_t shim_write(uint64_t context, const uint8_t *key,
                          uint32_t key_len, const uint8_t *data, uint32_t len,
                          uint32_t delete_value) {
    (void)context;
    (void)key;
    (void)key_len;
    (void)data;
    (void)len;
    (void)delete_value;
    return 0;
}

static void shim_release(uint64_t context, uint8_t *data, uint32_t len) {
    (void)context;
    (void)data;
    (void)len;
}

/* Result codes handed to Java. 0 means every ABI call succeeded. */
#define SHIM_OK 0
#define SHIM_ERR_LOAD 1
#define SHIM_ERR_ABI 2
#define SHIM_ERR_NEW 3
#define SHIM_ERR_STATUS 4
#define SHIM_ERR_CLOSE 5
#define SHIM_ERR_RELEASE 6
#define SHIM_ERR_CONFIG 7
/* The status JSON is written beside the diagnose snapshot so the host can
 * read both even if the process dies afterwards. */
static void write_status(const char *directory, const uint8_t *buffer,
                         uint32_t length) {
    char path[4200];
    int written = snprintf(path, sizeof(path), "%s/hp-probe-abi-status.json",
                           directory);
    if (written <= 0 || written >= (int)sizeof(path)) return;
    FILE *file = fopen(path, "wb");
    if (!file) return;
    fwrite(buffer, 1, length, file);
    fclose(file);
}

/* Evidence of which mapped object provided hp_ts_node_new: the canonical
 * path of the library, not the path the caller believed it loaded.
 *
 * The evidence directory is a fixed app-private path, not the node's
 * runtime directory: if the getter aborts, nothing else gets written, and
 * the host must still find the proof. */
static void write_library_path(const char *evidence_dir, const char *mapped) {
    char path[4200];
    int written = snprintf(path, sizeof(path), "%s/hp-probe-abi-library.txt",
                           evidence_dir);
    if (written <= 0 || written >= (int)sizeof(path)) return;
    FILE *file = fopen(path, "wb");
    if (!file) return;
    fwrite(mapped, 1, strlen(mapped), file);
    fclose(file);
}

static void write_mapped_path(const char *evidence_dir, void *symbol) {
    Dl_info info;
    memset(&info, 0, sizeof(info));
    if (dladdr(symbol, &info) == 0 || !info.dli_fname) {
        write_library_path(evidence_dir, "");
        return;
    }
    char resolved[PATH_MAX];
    const char *name = info.dli_fname;
    if (realpath(name, resolved) != NULL) name = resolved;
    write_library_path(evidence_dir, name);
}

JNIEXPORT jint JNICALL
Java_org_herdr_network_AbiProbeInstrumentation_nativeRun(
        JNIEnv *env, jclass cls, jstring library_path, jstring directory,
        jstring hostname, jstring control_url, jstring evidence_dir) {
    (void)cls;
    if (!library_path || !directory || !hostname || !control_url || !evidence_dir)
        return SHIM_ERR_CONFIG;

    const char *lib = (*env)->GetStringUTFChars(env, library_path, NULL);
    const char *dir = (*env)->GetStringUTFChars(env, directory, NULL);
    const char *host = (*env)->GetStringUTFChars(env, hostname, NULL);
    const char *control = (*env)->GetStringUTFChars(env, control_url, NULL);
    const char *evidence = (*env)->GetStringUTFChars(env, evidence_dir, NULL);
    if (!lib || !dir || !host || !control || !evidence) {
        if (lib) (*env)->ReleaseStringUTFChars(env, library_path, lib);
        if (dir) (*env)->ReleaseStringUTFChars(env, directory, dir);
        if (host) (*env)->ReleaseStringUTFChars(env, hostname, host);
        if (control) (*env)->ReleaseStringUTFChars(env, control_url, control);
        if (evidence) (*env)->ReleaseStringUTFChars(env, evidence_dir, evidence);
        return SHIM_ERR_CONFIG;
    }

    jint result = SHIM_OK;
    void *handle = dlopen(lib, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        result = SHIM_ERR_LOAD;
        goto done;
    }

    abi_version_fn abi_version = (abi_version_fn)dlsym(handle, "hp_ts_abi_version");
    node_new_fn node_new = (node_new_fn)dlsym(handle, "hp_ts_node_new");
    node_status_fn node_status = (node_status_fn)dlsym(handle, "hp_ts_node_status");
    node_close_fn node_close = (node_close_fn)dlsym(handle, "hp_ts_node_close");
    node_release_fn node_release = (node_release_fn)dlsym(handle, "hp_ts_node_release");
    if (!abi_version || !node_new || !node_status || !node_close || !node_release) {
        result = SHIM_ERR_LOAD;
        goto done;
    }
    /* Record which mapped object actually provides hp_ts_node_new before
     * any Go call, into the fixed evidence directory: if the getter aborts,
     * this file is the only proof that survives. */
    write_mapped_path(evidence, (void *)node_new);
    if (abi_version() != 1) {
        result = SHIM_ERR_ABI;
        goto done;
    }

    {
        char config[8192];
        int written = snprintf(config, sizeof(config),
                               "{\"directory\":\"%s\",\"hostname\":\"%s\",\"control_url\":\"%s\"}",
                               dir, host, control);
        if (written <= 0 || written >= (int)sizeof(config)) {
            result = SHIM_ERR_CONFIG;
            goto done;
        }
        hp_ts_store_callbacks store;
        store.read = shim_read;
        store.write = shim_write;
        store.release = shim_release;

        uint64_t node = 0;
        int32_t code = node_new((uint8_t *)config, (uint32_t)written, &store, 1,
                                &node);
        if (code != 0 || node == 0) {
            result = SHIM_ERR_NEW;
            goto done;
        }
        uint8_t buffer[8192];
        uint32_t length = 0;
        code = node_status(node, 5000, buffer, sizeof(buffer), &length);
        if (code != 0) {
            result = SHIM_ERR_STATUS;
        } else {
            write_status(dir, buffer, length);
        }
        if (node_close(node, 2000) != 0 && result == SHIM_OK) result = SHIM_ERR_CLOSE;
        if (node_release(node) != 0 && result == SHIM_OK) result = SHIM_ERR_RELEASE;
    }

done:
    (*env)->ReleaseStringUTFChars(env, library_path, lib);
    (*env)->ReleaseStringUTFChars(env, directory, dir);
    (*env)->ReleaseStringUTFChars(env, hostname, host);
    (*env)->ReleaseStringUTFChars(env, control_url, control);
    (*env)->ReleaseStringUTFChars(env, evidence_dir, evidence);
    return result;
}
