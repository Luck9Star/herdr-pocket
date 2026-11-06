// This production control plane is compiled against the pinned real libzt API.
// Tests inject only the engine symbols; they never start a ZeroTier node.
#include "hp_zt_manager.h"
#include "ZeroTierSockets.h"
#include <atomic>
#include <chrono>
#include <cstdint>
#include <limits>
#include <map>
#include <memory>
#include <mutex>

namespace {
using Clock = std::chrono::steady_clock;
struct Deadline {
    Clock::time_point end;
    explicit Deadline(uint32_t ms) : end(Clock::now() + std::chrono::milliseconds(ms)) {}
    bool expired() const { return Clock::now() >= end; }
    uint32_t remaining() const {
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - Clock::now()).count();
        if (ns <= 0) { return 0; }
        return static_cast<uint32_t>((ns + 999999) / 1000000);
    }
};
bool valid_timeout(uint32_t ms) { return ms && ms <= 60000; }
struct Network {
    uint64_t network;
    bool closing;
    bool joined;
};
struct Device {
    const uint64_t owner;
    const uint64_t public_id;
    std::timed_mutex control;
    std::atomic<bool> closing;
    uint32_t phase;
    bool touched_native;
    std::map<uint64_t, Network> networks;
    Device(uint64_t value, uint64_t id)
        : owner(value), public_id(id), closing(false), phase(HP_ZT_DEVICE_INITIALIZED), touched_native(false) {}
};
struct Registry {
    std::mutex mutex;
    uint64_t next_owner = 1;
    uint64_t next_network = 1;
    std::shared_ptr<Device> device;
};
// Intentionally process-lifetime: cannot destroy a live device on DSO unload.
// The embedding host must keep this candidate library loaded while in use.
Registry& registry() { static Registry *r = new Registry; return *r; }
std::shared_ptr<Device> find(uint64_t owner) {
    auto& r = registry();
    std::lock_guard<std::mutex> guard(r.mutex);
    return r.device && r.device->owner == owner ? r.device : nullptr;
}
bool current(const std::shared_ptr<Device>& device) {
    auto& r = registry();
    std::lock_guard<std::mutex> guard(r.mutex);
    return r.device == device;
}
uint64_t next_lease() {
    auto& r = registry();
    std::lock_guard<std::mutex> guard(r.mutex);
    if (r.next_network == std::numeric_limits<uint64_t>::max()) { return 0; }
    return r.next_network++;
}
int acquire(const std::shared_ptr<Device>& device, Deadline& deadline,
            std::unique_lock<std::timed_mutex>& lock, bool maintenance = false) {
    if (!lock.try_lock_until(deadline.end)) { return HP_ZT_MANAGED_TIMEOUT; }
    if (!current(device)) { return HP_ZT_MANAGED_STALE; }
    if (!maintenance && device->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
    return HP_ZT_MANAGED_OK;
}
int after_call(const std::shared_ptr<Device>& d, Deadline& deadline, int result) {
    if (d->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
    if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
    return result == ZTS_ERR_OK ? HP_ZT_MANAGED_OK : HP_ZT_MANAGED_NATIVE;
}
int online(const std::shared_ptr<Device>& d) {
    // A different actual identity is not an acceptable restarted replacement.
    return zts_node_is_online() == 1 && zts_node_get_id() == d->public_id;
}
uint32_t phase_for(int status) {
    switch (status) {
    case 0: return HP_ZT_NETWORK_REQUESTING;
    case 1: return HP_ZT_NETWORK_CONFIGURED;
    case 2: return HP_ZT_NETWORK_DENIED;
    case 3: return HP_ZT_NETWORK_NOT_FOUND;
    case 4: return HP_ZT_NETWORK_PORT_ERROR;
    case 5: return HP_ZT_NETWORK_CLIENT_OLD;
    case 6: return HP_ZT_NETWORK_AUTH_REQUIRED;
    default: return HP_ZT_NETWORK_UNKNOWN;
    }
}
}

extern "C" {
uint32_t hp_zt_manager_abi_version() { return HP_ZT_MANAGER_ABI_VERSION; }
int hp_zt_device_new(const uint8_t *identity, size_t length, uint32_t ms, uint64_t *out) {
    if (out) { *out = 0; }
    if (!out || !identity || length != HP_ZT_IDENTITY_BYTES || !valid_timeout(ms)) {
        return HP_ZT_MANAGED_ARGUMENT;
    }
    std::shared_ptr<Device> d;
    try {
        Deadline deadline(ms);
        auto& r = registry();
        { std::lock_guard<std::mutex> guard(r.mutex);
          if (r.device) { return HP_ZT_MANAGED_BUSY; } }
        uint64_t id = 0;
        if (hp_zt_identity_validate(identity, length, &id) != HP_ZT_OK || !id) {
            return HP_ZT_MANAGED_IDENTITY;
        }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        {
            std::lock_guard<std::mutex> guard(r.mutex);
            if (r.device) { return HP_ZT_MANAGED_BUSY; }
            if (r.next_owner == std::numeric_limits<uint64_t>::max()) { return HP_ZT_MANAGED_CAPACITY; }
            d = std::make_shared<Device>(r.next_owner++, id);
            // Reserve BEFORE touching global engine state, including failed init.
            r.device = d;
            *out = d->owner;
        }
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock);
        if (result) { return result; }
        // A foreign raw libzt caller is never adopted by this manager.
        if (hp_zt_node_quiescent() != 1) {
            d->phase = HP_ZT_DEVICE_FAULTED;
            d->closing.store(true);
            return HP_ZT_MANAGED_BUSY;
        }
        if (d->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        d->touched_native = true;
        result = zts_init_from_memory(reinterpret_cast<const char*>(identity), static_cast<unsigned>(length));
        if (result == ZTS_ERR_OK) { result = zts_init_allow_id_cache(0); }
        if (result == ZTS_ERR_OK) { result = zts_init_allow_net_cache(0); }
        if (result == ZTS_ERR_OK) { result = zts_init_allow_peer_cache(0); }
        if (result == ZTS_ERR_OK) { result = zts_init_allow_roots_cache(0); }
        if (result != ZTS_ERR_OK || deadline.expired() || d->closing.load()) {
            d->phase = HP_ZT_DEVICE_FAULTED;
            d->closing.store(true);
            return deadline.expired() ? HP_ZT_MANAGED_TIMEOUT : HP_ZT_MANAGED_NATIVE;
        }
        return HP_ZT_MANAGED_OK;
    } catch (...) {
        if (d) { d->closing.store(true); }
        return HP_ZT_MANAGED_NATIVE;
    }
}
int hp_zt_device_start(uint64_t owner, uint32_t ms) {
    if (!owner || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock);
        if (result) { return result; }
        // Unknown/late start is never replayed. The only recovery is stop.
        if (d->phase != HP_ZT_DEVICE_INITIALIZED) { return HP_ZT_MANAGED_BUSY; }
        d->phase = HP_ZT_DEVICE_FAULTED;
        result = zts_node_start();
        result = after_call(d, deadline, result);
        if (result) { d->closing.store(true); return result; }
        d->phase = HP_ZT_DEVICE_STARTED;
        return HP_ZT_MANAGED_OK;
    } catch (...) { d->closing.store(true); return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_device_status(uint64_t owner, uint32_t ms, uint32_t *phase,
                        uint32_t *is_online, uint64_t *node_id) {
    if (phase) { *phase = 0; } if (is_online) { *is_online = 0; } if (node_id) { *node_id = 0; }
    if (!owner || !valid_timeout(ms) || !phase || !is_online || !node_id) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock, true);
        if (result) { return result; }
        uint32_t active = d->phase == HP_ZT_DEVICE_STARTED && !d->closing.load() ? online(d) : 0;
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        *phase = d->phase == HP_ZT_DEVICE_STOPPED ? d->phase :
            (d->closing.load() ? static_cast<uint32_t>(HP_ZT_DEVICE_CLOSING) : d->phase);
        *is_online = d->closing.load() ? 0 : active;
        *node_id = d->public_id;
        return HP_ZT_MANAGED_OK;
    } catch (...) { return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_device_stop(uint64_t owner, uint32_t ms) {
    if (!owner || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    // Immediate admission fence even if an original engine call returns late.
    d->closing.store(true);
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock, true);
        if (result) { return result; }
        if (d->phase == HP_ZT_DEVICE_STOPPED) { return HP_ZT_MANAGED_OK; }
        d->phase = HP_ZT_DEVICE_CLOSING;
        for (auto& entry : d->networks) { entry.second.closing = true; }
        if (!d->touched_native) {
            // A foreign raw node was rejected, or initialization never entered.
            // Do not stop somebody else's process-global engine.
            d->networks.clear();
            d->phase = HP_ZT_DEVICE_STOPPED;
            return HP_ZT_MANAGED_OK;
        }
        uint32_t remaining = deadline.remaining();
        if (!remaining) { return HP_ZT_MANAGED_TIMEOUT; }
        result = hp_zt_node_stop(remaining);
        if (result != HP_ZT_OK || hp_zt_node_quiescent() != 1) {
            return result == HP_ZT_TIMEOUT ? HP_ZT_MANAGED_TIMEOUT : HP_ZT_MANAGED_NATIVE;
        }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        d->networks.clear();
        d->phase = HP_ZT_DEVICE_STOPPED;
        return HP_ZT_MANAGED_OK;
    } catch (...) { return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_device_release(uint64_t owner, uint32_t ms) {
    if (!owner || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock, true);
        if (result) { return result; }
        if (d->phase != HP_ZT_DEVICE_STOPPED || !d->networks.empty()
                || (d->touched_native && hp_zt_node_quiescent() != 1)) {
            return HP_ZT_MANAGED_BUSY;
        }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        auto& r = registry();
        std::lock_guard<std::mutex> guard(r.mutex);
        if (r.device != d) { return HP_ZT_MANAGED_STALE; }
        r.device.reset();
        return HP_ZT_MANAGED_OK;
    } catch (...) { return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_network_join(uint64_t owner, uint64_t network, uint32_t ms, uint64_t *out) {
    if (out) { *out = 0; }
    if (!owner || !network || !out || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock);
        if (result) { return result; }
        if (d->phase != HP_ZT_DEVICE_STARTED || !online(d)) { return HP_ZT_MANAGED_NOT_ONLINE; }
        // Online can wait in the original engine. A stop requested while it was
        // pending must not be followed by a new join side effect.
        if (d->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        if (d->networks.size() >= HP_ZT_MAX_NETWORK_LEASES) { return HP_ZT_MANAGED_CAPACITY; }
        bool joined = false;
        for (const auto& entry : d->networks) {
            if (entry.second.network == network) {
                if (entry.second.closing || !entry.second.joined) { return HP_ZT_MANAGED_BUSY; }
                joined = true;
            }
        }
        uint64_t lease = next_lease();
        if (!lease) { return HP_ZT_MANAGED_CAPACITY; }
        d->networks.emplace(lease, Network{network, false, joined});
        *out = lease;
        if (!joined) {
            result = zts_net_join(network);
            result = after_call(d, deadline, result);
            auto& entry = d->networks.at(lease);
            if (result) { entry.closing = true; return result; }
            entry.joined = true;
        }
        if (d->closing.load()) { d->networks.at(lease).closing = true; return HP_ZT_MANAGED_CLOSING; }
        return HP_ZT_MANAGED_OK;
    } catch (...) { d->closing.store(true); return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_network_status(uint64_t owner, uint64_t lease, uint32_t ms, uint32_t *phase, uint32_t *is_online) {
    if (phase) { *phase = 0; } if (is_online) { *is_online = 0; }
    if (!owner || !lease || !valid_timeout(ms) || !phase || !is_online) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock, true);
        if (result) { return result; }
        auto it = d->networks.find(lease);
        if (it == d->networks.end()) { return HP_ZT_MANAGED_STALE; }
        if (d->closing.load() || it->second.closing) { *phase = HP_ZT_NETWORK_CLOSING; return HP_ZT_MANAGED_OK; }
        uint32_t active = online(d);
        uint32_t status = active ? phase_for(zts_net_get_status(it->second.network)) : HP_ZT_NETWORK_UNKNOWN;
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        if (d->closing.load()) { *phase = HP_ZT_NETWORK_CLOSING; return HP_ZT_MANAGED_OK; }
        *is_online = active;
        *phase = status;
        return HP_ZT_MANAGED_OK;
    } catch (...) { return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_network_leave(uint64_t owner, uint64_t lease, uint32_t ms) {
    if (!owner || !lease || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d = find(owner);
    if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock);
        if (result) { return result; }
        auto it = d->networks.find(lease);
        if (it == d->networks.end()) { return HP_ZT_MANAGED_STALE; }
        it->second.closing = true;
        const uint64_t network = it->second.network;
        bool other = false;
        for (const auto& entry : d->networks) {
            if (entry.first != lease && entry.second.network == network) { other = true; }
        }
        if (!other) {
            result = after_call(d, deadline, zts_net_leave(network));
            if (result) { return result; }
        }
        d->networks.erase(it);
        return HP_ZT_MANAGED_OK;
    } catch (...) { d->closing.store(true); return HP_ZT_MANAGED_NATIVE; }
}
}
