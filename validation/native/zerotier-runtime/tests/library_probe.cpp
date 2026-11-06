#include "hp_zt_manager.h"
#include <cstdint>
#include <cstdio>

namespace {
void erase_secret(uint8_t *bytes, size_t length) {
    volatile uint8_t *p = bytes;
    while (length--) { *p++ = 0; }
}

bool check(int condition, const char *label, int code = 0) {
    if (condition) { return true; }
    std::fprintf(stderr, "%s failed (code=%d)\n", label, code);
    return false;
}

bool probe_one_identity(uint8_t *identity, uint64_t expected_node_id) {
    uint64_t owner = 0;
    int result = hp_zt_device_new(identity, HP_ZT_IDENTITY_BYTES, 10000, &owner);
    if (!check(result == HP_ZT_MANAGED_OK && owner != 0,
               "device_new", result)) {
        if (owner != 0) {
            const int stop = hp_zt_device_stop(owner, 10000);
            if (stop == HP_ZT_MANAGED_OK) {
                hp_zt_device_release(owner, 10000);
            }
        }
        return false;
    }

    uint32_t phase = 0;
    uint32_t online = 1;
    uint64_t public_node_id = 0;
    result = hp_zt_device_status(owner, 10000, &phase, &online, &public_node_id);
    bool ok = check(result == HP_ZT_MANAGED_OK, "offline status", result)
        && check(phase == HP_ZT_DEVICE_INITIALIZED, "initialized phase", (int)phase)
        && check(online == 0, "offline node", (int)online)
        && check(public_node_id == expected_node_id, "identity node id", 0);

    result = hp_zt_device_stop(owner, 10000);
    ok = check(result == HP_ZT_MANAGED_OK, "stop before node_start", result) && ok;
    result = hp_zt_device_release(owner, 10000);
    ok = check(result == HP_ZT_MANAGED_OK, "release after quiescent stop", result) && ok;
    return ok;
}
}

int main() {
    if (!check(hp_zt_manager_abi_version() == HP_ZT_MANAGER_ABI_VERSION,
               "manager ABI")) {
        return 1;
    }
    if (!check(hp_zt_abi_version() == HP_ZT_ABI_VERSION, "native ABI")) {
        return 1;
    }

    for (unsigned int iteration = 0; iteration != 2; ++iteration) {
        uint8_t identity[HP_ZT_IDENTITY_WORK_BYTES] = {};
        size_t length = 0;
        uint64_t node_id = 0;
        int result = hp_zt_identity_create(identity, sizeof(identity), &length, &node_id);
        bool ok = check(result == HP_ZT_OK, "identity create", result)
            && check(length == HP_ZT_IDENTITY_BYTES, "canonical identity length",
                     static_cast<int>(length))
            && check(node_id != 0, "identity node id");
        if (ok) {
            uint64_t validated_node_id = 0;
            result = hp_zt_identity_validate(identity, length, &validated_node_id);
            ok = check(result == HP_ZT_OK, "identity validate", result)
                && check(validated_node_id == node_id, "validated node id");
        }
        if (ok) { ok = probe_one_identity(identity, node_id); }
        erase_secret(identity, sizeof(identity));
        if (!ok) { return 1; }
    }

    std::puts("native library probe passed: ABI, transient identity validation, "
              "offline init/stop/release repeated twice; node_started=false");
    return 0;
}
