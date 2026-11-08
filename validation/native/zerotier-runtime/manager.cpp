// This production control plane is compiled against the pinned real libzt API.
// Tests inject only the engine symbols; they never start a ZeroTier node.
#include "hp_zt_manager.h"
#include "ZeroTierSockets.h"
#include "hp_zt_bound.h"
#include <array>
#include <condition_variable>
#include <cstring>
#include <thread>
#include <vector>
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
struct LeaseFence { std::atomic<bool> closing{false}; };
struct Stream {
    const uint64_t handle, lease, network;
    const std::shared_ptr<LeaseFence> fence;
    std::array<uint8_t,16> ip{};
    uint32_t ip_len;
    uint16_t port;
    std::mutex state;
    std::condition_variable changed;
    std::timed_mutex native, cleanup;
    std::atomic<bool> cancelled{false};
    unsigned active=0;
    bool attempted=false, opened=false, closed=false, read_busy=false, write_busy=false, write_shut=false;
    int fd=-1;
    uint64_t epoch=0;
    Stream(uint64_t h,uint64_t l,uint64_t n,std::shared_ptr<LeaseFence> f,
           const uint8_t* data,uint32_t size,uint16_t service)
        : handle(h),lease(l),network(n),fence(f),ip_len(size),port(service) {
        std::memcpy(ip.data(),data,size);
    }
};
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
    std::mutex streams_mutex;
    std::map<uint64_t,std::shared_ptr<LeaseFence>> fences;
    std::map<uint64_t,std::shared_ptr<Stream>> streams;
    Device(uint64_t value, uint64_t id)
        : owner(value), public_id(id), closing(false), phase(HP_ZT_DEVICE_INITIALIZED), touched_native(false) {}
};
struct Registry {
    std::mutex mutex;
    uint64_t next_owner = 1;
    uint64_t next_network = 1;
    uint64_t next_stream = 1;
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
    while (!lock.try_lock_for(std::chrono::milliseconds(2))) {
        if (!maintenance && device->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
    }
    if (!current(device)) { return HP_ZT_MANAGED_STALE; }
    if (!maintenance && device->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
    if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
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
std::shared_ptr<Stream> find_stream(const std::shared_ptr<Device>& d,uint64_t lease,uint64_t handle) {
    std::lock_guard<std::mutex> lock(d->streams_mutex);
    auto it=d->streams.find(handle);
    return it!=d->streams.end() && it->second->lease==lease ? it->second : nullptr;
}
bool retiring(const std::shared_ptr<Device>& d,const std::shared_ptr<Stream>& s) {
    return d->closing.load() || s->fence->closing.load() || s->cancelled.load();
}
void cancel_stream(const std::shared_ptr<Stream>& s) {
    s->cancelled.store(true); s->changed.notify_all();
}
std::vector<std::shared_ptr<Stream>> selected_streams(const std::shared_ptr<Device>& d,uint64_t lease=0) {
    std::vector<std::shared_ptr<Stream>> result;
    std::lock_guard<std::mutex> lock(d->streams_mutex);
    for (const auto& entry:d->streams) {
        if (!lease || entry.second->lease==lease) { result.push_back(entry.second); }
    }
    return result;
}
void cancel_streams(const std::shared_ptr<Device>& d,uint64_t lease=0) {
    std::lock_guard<std::mutex> lock(d->streams_mutex);
    for (const auto& entry:d->streams) {
        if (!lease || entry.second->lease==lease) { cancel_stream(entry.second); }
    }
}
// Counts admission BEFORE a possible native wait. Every original FFI and buffer
// remains owned until this exact guard exits, including a late return.
struct StreamCall {
    std::shared_ptr<Stream> stream;
    int direction; // 0=open, 1=read, 2=write/shutdown
    bool admitted=false;
    StreamCall(std::shared_ptr<Stream> s,int dir):stream(s),direction(dir) {}
    int admit(const std::shared_ptr<Device>& d) {
        std::lock_guard<std::mutex> lock(stream->state);
        if (retiring(d,stream) || stream->closed) { return HP_ZT_MANAGED_CANCELLED; }
        if (direction==0) {
            if (stream->attempted || stream->active) { return HP_ZT_MANAGED_BUSY; }
            stream->attempted=true;
        } else {
            if (!stream->opened) { return HP_ZT_MANAGED_BUSY; }
            bool& busy=direction==1 ? stream->read_busy : stream->write_busy;
            if (busy) { return HP_ZT_MANAGED_BUSY; }
            if (direction==2 && stream->write_shut) { return HP_ZT_MANAGED_CLOSING; }
            busy=true;
        }
        ++stream->active; admitted=true; return HP_ZT_MANAGED_OK;
    }
    ~StreamCall() {
        if (!admitted) { return; }
        { std::lock_guard<std::mutex> lock(stream->state);
          --stream->active;
          if (direction==1) { stream->read_busy=false; }
          if (direction==2) { stream->write_busy=false; } }
        stream->changed.notify_all();
    }
};
int native_lock(const std::shared_ptr<Device>& d,const std::shared_ptr<Stream>& s,
                Deadline& deadline,std::unique_lock<std::timed_mutex>& lock) {
    while (!lock.try_lock_for(std::chrono::milliseconds(2))) {
        if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
    }
    if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
    return deadline.expired() ? HP_ZT_MANAGED_TIMEOUT : HP_ZT_MANAGED_OK;
}
void wait_stream(const std::shared_ptr<Device>& d,const std::shared_ptr<Stream>& s,Deadline& deadline) {
    std::unique_lock<std::mutex> lock(s->state);
    s->changed.wait_until(lock,std::min(deadline.end,Clock::now()+std::chrono::milliseconds(5)),
                         [&]{return retiring(d,s);});
}
int close_stream(const std::shared_ptr<Stream>& s,Deadline& deadline) {
    cancel_stream(s);
    std::unique_lock<std::timed_mutex> cleanup(s->cleanup,std::defer_lock);
    if (!cleanup.try_lock_until(deadline.end)) { return HP_ZT_MANAGED_TIMEOUT; }
    {
        std::unique_lock<std::mutex> lock(s->state);
        if (!s->changed.wait_until(lock,deadline.end,[&]{return s->active==0;})) { return HP_ZT_MANAGED_TIMEOUT; }
        if (s->closed) { return HP_ZT_MANAGED_OK; }
    }
    if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
    // No admitted operation remains and cancellation fences future admission.
    const int result=s->fd<0 ? HP_ZT_BOUND_OK : hp_zt_bound_close(s->fd);
    if (result!=HP_ZT_BOUND_OK) { return HP_ZT_MANAGED_NATIVE; }
    { std::lock_guard<std::mutex> lock(s->state); s->fd=-1; s->closed=true; s->opened=false; }
    return deadline.expired() ? HP_ZT_MANAGED_TIMEOUT : HP_ZT_MANAGED_OK;
}
int drain_streams(const std::shared_ptr<Device>& d,Deadline& deadline,uint64_t lease=0) {
    const auto streams=selected_streams(d,lease);
    for (const auto& s:streams) { cancel_stream(s); }
    for (const auto& s:streams) { int code=close_stream(s,deadline); if (code) { return code; } }
    return HP_ZT_MANAGED_OK;
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
    cancel_streams(d);
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
            { std::lock_guard<std::mutex> streams(d->streams_mutex); d->fences.clear(); }
            d->phase = HP_ZT_DEVICE_STOPPED;
            return HP_ZT_MANAGED_OK;
        }
        result = drain_streams(d,deadline);
        if (result) { return result; }
        uint32_t remaining = deadline.remaining();
        if (!remaining) { return HP_ZT_MANAGED_TIMEOUT; }
        result = hp_zt_node_stop(remaining);
        if (result != HP_ZT_OK || hp_zt_node_quiescent() != 1) {
            return result == HP_ZT_TIMEOUT ? HP_ZT_MANAGED_TIMEOUT : HP_ZT_MANAGED_NATIVE;
        }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        d->networks.clear();
            { std::lock_guard<std::mutex> streams(d->streams_mutex); d->fences.clear(); }
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
        { std::lock_guard<std::mutex> streams(d->streams_mutex);
          if (!d->streams.empty()) { return HP_ZT_MANAGED_BUSY; } }
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
        if (d->phase != HP_ZT_DEVICE_STARTED) { return HP_ZT_MANAGED_NOT_ONLINE; }
        while (true) {
            const uint64_t id=zts_node_get_id();
            if (d->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
            if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
            if (id==d->public_id) { break; }
            if (id && id<0x10000000000ULL) { return HP_ZT_MANAGED_NOT_ONLINE; }
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
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
        { std::lock_guard<std::mutex> streams(d->streams_mutex);
          d->fences.emplace(lease,std::make_shared<LeaseFence>()); }
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
        uint32_t status = active ? phase_for(zts_net_get_status(it->second.network)) : HP_ZT_NETWORK_REQUESTING;
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
    { std::lock_guard<std::mutex> streams(d->streams_mutex);
      auto it=d->fences.find(lease);
      if (it==d->fences.end()) { return HP_ZT_MANAGED_STALE; }
      it->second->closing.store(true); }
    cancel_streams(d,lease);
    try {
        Deadline deadline(ms);
        std::unique_lock<std::timed_mutex> lock(d->control, std::defer_lock);
        int result = acquire(d, deadline, lock);
        if (result) { return result; }
        auto it = d->networks.find(lease);
        if (it == d->networks.end()) { return HP_ZT_MANAGED_STALE; }
        it->second.closing = true;
        result=drain_streams(d,deadline,lease);
        if (result) { return result; }
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
        { std::lock_guard<std::mutex> streams(d->streams_mutex); d->fences.erase(lease); }
        return HP_ZT_MANAGED_OK;
    } catch (...) { d->closing.store(true); return HP_ZT_MANAGED_NATIVE; }
}
uint32_t hp_zt_stream_abi_version() { return HP_ZT_STREAM_ABI_VERSION; }
int hp_zt_stream_new(uint64_t owner,uint64_t lease,const uint8_t* ip,uint32_t length,uint16_t port,uint64_t* out) {
    if (out) { *out=0; }
    if (!owner || !lease || !ip || (length!=4 && length!=16) || !port || !out) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    try {
        std::unique_lock<std::timed_mutex> control(d->control,std::try_to_lock);
        if (!control.owns_lock()) { return HP_ZT_MANAGED_BUSY; }
        if (!current(d)) { return HP_ZT_MANAGED_STALE; }
        if (d->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
        auto network=d->networks.find(lease);
        if (network==d->networks.end()) { return HP_ZT_MANAGED_STALE; }
        if (!network->second.joined || network->second.closing) { return HP_ZT_MANAGED_CLOSING; }
        std::lock_guard<std::mutex> lock(d->streams_mutex);
        auto fence=d->fences.find(lease);
        if (fence==d->fences.end() || fence->second->closing.load()) { return HP_ZT_MANAGED_CLOSING; }
        if (d->streams.size()>=HP_ZT_MAX_STREAMS) { return HP_ZT_MANAGED_CAPACITY; }
        uint64_t handle=0;
        { auto& r=registry(); std::lock_guard<std::mutex> global(r.mutex);
          if (r.next_stream==std::numeric_limits<uint64_t>::max()) { return HP_ZT_MANAGED_CAPACITY; }
          handle=r.next_stream++; }
        auto s=std::make_shared<Stream>(handle,lease,network->second.network,fence->second,ip,length,port);
        d->streams.emplace(handle,s); *out=handle; return HP_ZT_MANAGED_OK;
    } catch (...) { return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_stream_open(uint64_t owner,uint64_t lease,uint64_t handle,uint32_t ms) {
    if (!owner || !lease || !handle || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    auto s=find_stream(d,lease,handle); if (!s) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms); StreamCall call(s,0); int result=call.admit(d); if (result) { return result; }
        {
            std::unique_lock<std::timed_mutex> control(d->control,std::defer_lock);
            while (!control.try_lock_for(std::chrono::milliseconds(2))) {
                if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
                if (deadline.expired()) { cancel_stream(s); return HP_ZT_MANAGED_TIMEOUT; }
            }
            if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
            auto n=d->networks.find(lease);
            if (n==d->networks.end()) { cancel_stream(s); return HP_ZT_MANAGED_STALE; }
            if (d->phase!=HP_ZT_DEVICE_STARTED || !online(d)) { cancel_stream(s); return HP_ZT_MANAGED_NOT_ONLINE; }
            if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
            if (deadline.expired()) { cancel_stream(s); return HP_ZT_MANAGED_TIMEOUT; }
        }
        {
            std::unique_lock<std::timed_mutex> native(s->native,std::defer_lock);
            result=native_lock(d,s,deadline,native); if (result) { cancel_stream(s); return result; }
            int fd=-1; uint64_t epoch=0;
            result=hp_zt_bound_open(s->network,s->ip.data(),s->ip_len,s->port,&fd,&epoch);
            // Even a failed/late/cancelled call may have allocated an original fd.
            { std::lock_guard<std::mutex> lock(s->state); s->fd=fd; s->epoch=epoch; }
        }
        if (result!=HP_ZT_BOUND_OK && result!=HP_ZT_BOUND_AGAIN) {
            cancel_stream(s); return result==HP_ZT_BOUND_ROUTE ? HP_ZT_MANAGED_ROUTE : HP_ZT_MANAGED_NATIVE;
        }
        while (true) {
            if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
            if (deadline.expired()) { cancel_stream(s); return HP_ZT_MANAGED_TIMEOUT; }
            {
                std::unique_lock<std::timed_mutex> native(s->native,std::defer_lock);
                result=native_lock(d,s,deadline,native); if (result) { cancel_stream(s); return result; }
                result=hp_zt_bound_state(s->fd,s->network,s->epoch);
            }
            if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
            if (deadline.expired()) { cancel_stream(s); return HP_ZT_MANAGED_TIMEOUT; }
            if (result==HP_ZT_BOUND_OK) {
                std::lock_guard<std::mutex> lock(s->state); s->opened=true; return HP_ZT_MANAGED_OK;
            }
            if (result!=HP_ZT_BOUND_AGAIN) {
                cancel_stream(s); return result==HP_ZT_BOUND_ROUTE ? HP_ZT_MANAGED_ROUTE : HP_ZT_MANAGED_NATIVE;
            }
            wait_stream(d,s,deadline);
        }
    } catch (...) { cancel_stream(s); return HP_ZT_MANAGED_NATIVE; }
}
int stream_io(uint64_t owner,uint64_t lease,uint64_t handle,void* data,uint32_t length,uint32_t ms,uint32_t* count,bool writing) {
    if (count) { *count=0; }
    if (!owner || !lease || !handle || !data || !length || length>HP_ZT_MAX_IO_BYTES || !count || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    auto s=find_stream(d,lease,handle); if (!s) { return HP_ZT_MANAGED_STALE; }
    bool dispatched=false;
    try {
        Deadline deadline(ms); StreamCall call(s,writing ? 2 : 1); int result=call.admit(d); if (result) { return result; }
        while (true) {
            if (retiring(d,s)) { return writing && dispatched ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_CANCELLED; }
            if (deadline.expired()) {
                if (writing && dispatched) { cancel_stream(s); return HP_ZT_MANAGED_UNKNOWN_WRITE; }
                return HP_ZT_MANAGED_TIMEOUT;
            }
            uint32_t transferred=0;
            {
                std::unique_lock<std::timed_mutex> native(s->native,std::defer_lock);
                result=native_lock(d,s,deadline,native);
                if (result) {
                    if (writing && dispatched) { cancel_stream(s); return HP_ZT_MANAGED_UNKNOWN_WRITE; }
                    return result;
                }
                result=hp_zt_bound_state(s->fd,s->network,s->epoch);
                if (retiring(d,s)) { return writing && dispatched ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_CANCELLED; }
                if (deadline.expired()) {
                if (writing && dispatched) { cancel_stream(s); return HP_ZT_MANAGED_UNKNOWN_WRITE; }
                return HP_ZT_MANAGED_TIMEOUT;
            }
                if (result!=HP_ZT_BOUND_OK) {
                    cancel_stream(s); return writing && dispatched ? HP_ZT_MANAGED_UNKNOWN_WRITE :
                        (result==HP_ZT_BOUND_ROUTE ? HP_ZT_MANAGED_ROUTE : HP_ZT_MANAGED_NATIVE);
                }
                dispatched=true;
                result=writing ? hp_zt_bound_write(s->fd,static_cast<const uint8_t*>(data),length,&transferred) :
                                 hp_zt_bound_read(s->fd,static_cast<uint8_t*>(data),length,&transferred);
            }
            if (transferred>length || (result!=HP_ZT_BOUND_OK && transferred)) {
                cancel_stream(s); return writing ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_CANCELLED;
            }
            if (retiring(d,s)) { return writing ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_CANCELLED; }
            if (deadline.expired()) {
                if (writing) { cancel_stream(s); return HP_ZT_MANAGED_UNKNOWN_WRITE; }
                if (transferred || result!=HP_ZT_BOUND_AGAIN) { cancel_stream(s); return HP_ZT_MANAGED_CANCELLED; }
                // Original recv really ended and consumed zero: retryable timeout.
                return HP_ZT_MANAGED_TIMEOUT;
            }
            // Recheck epoch after consuming data; config change can invalidate a
            // completed read, but can never send on another generation's netif.
            {
                std::unique_lock<std::timed_mutex> native(s->native,std::defer_lock);
                const int locked=native_lock(d,s,deadline,native);
                if (locked) { return writing ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_CANCELLED; }
                if (hp_zt_bound_state(s->fd,s->network,s->epoch)!=HP_ZT_BOUND_OK) {
                    cancel_stream(s); return writing ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_ROUTE;
                }
            }
            if (retiring(d,s)) { return writing ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_CANCELLED; }
            if (deadline.expired()) {
                if (writing) { cancel_stream(s); return HP_ZT_MANAGED_UNKNOWN_WRITE; }
                if (!transferred && result==HP_ZT_BOUND_AGAIN) { return HP_ZT_MANAGED_TIMEOUT; }
                cancel_stream(s); return HP_ZT_MANAGED_CANCELLED;
            }
            if (result==HP_ZT_BOUND_OK) { *count=transferred; return HP_ZT_MANAGED_OK; }
            if (result!=HP_ZT_BOUND_AGAIN) { cancel_stream(s); return writing ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_NATIVE; }
            wait_stream(d,s,deadline);
        }
    } catch (...) { cancel_stream(s); return writing && dispatched ? HP_ZT_MANAGED_UNKNOWN_WRITE : HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_stream_read(uint64_t owner,uint64_t lease,uint64_t stream,uint8_t* data,uint32_t cap,uint32_t ms,uint32_t* count) {
    return stream_io(owner,lease,stream,data,cap,ms,count,false);
}
int hp_zt_stream_write(uint64_t owner,uint64_t lease,uint64_t stream,const uint8_t* data,uint32_t length,uint32_t ms,uint32_t* count) {
    return stream_io(owner,lease,stream,const_cast<uint8_t*>(data),length,ms,count,true);
}
int hp_zt_stream_shutdown_write(uint64_t owner,uint64_t lease,uint64_t handle,uint32_t ms) {
    if (!owner || !lease || !handle || !valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    auto s=find_stream(d,lease,handle); if (!s) { return HP_ZT_MANAGED_STALE; }
    try {
        Deadline deadline(ms);
        { std::lock_guard<std::mutex> lock(s->state);
          if (s->write_shut && !retiring(d,s)) { return HP_ZT_MANAGED_OK; } }
        StreamCall call(s,2); int result=call.admit(d); if (result) { return result; }
        std::unique_lock<std::timed_mutex> native(s->native,std::defer_lock);
        result=native_lock(d,s,deadline,native); if (result) { return result; }
        if (hp_zt_bound_state(s->fd,s->network,s->epoch)!=HP_ZT_BOUND_OK) { cancel_stream(s); return HP_ZT_MANAGED_ROUTE; }
        if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
        if (deadline.expired()) { return HP_ZT_MANAGED_TIMEOUT; }
        result=hp_zt_bound_shutdown_write(s->fd);
        if (result!=HP_ZT_BOUND_OK) { cancel_stream(s); return HP_ZT_MANAGED_NATIVE; }
        { std::lock_guard<std::mutex> lock(s->state); s->write_shut=true; }
        if (retiring(d,s)) { return HP_ZT_MANAGED_CANCELLED; }
        if (deadline.expired()) { cancel_stream(s); return HP_ZT_MANAGED_TIMEOUT; }
        return HP_ZT_MANAGED_OK;
    } catch (...) { cancel_stream(s); return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_stream_cancel(uint64_t owner,uint64_t lease,uint64_t handle) {
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    auto s=find_stream(d,lease,handle); if (!s) { return HP_ZT_MANAGED_STALE; }
    cancel_stream(s); return HP_ZT_MANAGED_OK;
}
int hp_zt_stream_close(uint64_t owner,uint64_t lease,uint64_t handle,uint32_t ms) {
    if (!valid_timeout(ms)) { return HP_ZT_MANAGED_ARGUMENT; }
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    auto s=find_stream(d,lease,handle); if (!s) { return HP_ZT_MANAGED_STALE; }
    try { Deadline deadline(ms); return close_stream(s,deadline); }
    catch (...) { cancel_stream(s); return HP_ZT_MANAGED_NATIVE; }
}
int hp_zt_stream_release(uint64_t owner,uint64_t lease,uint64_t handle) {
    auto d=find(owner); if (!d) { return HP_ZT_MANAGED_STALE; }
    auto s=find_stream(d,lease,handle); if (!s) { return HP_ZT_MANAGED_STALE; }
    try {
        std::unique_lock<std::timed_mutex> cleanup(s->cleanup,std::try_to_lock);
        if (!cleanup.owns_lock()) { return HP_ZT_MANAGED_BUSY; }
        { std::lock_guard<std::mutex> state(s->state);
          if (!s->closed || s->active) { return HP_ZT_MANAGED_BUSY; } }
        std::lock_guard<std::mutex> lock(d->streams_mutex);
        auto it=d->streams.find(handle);
        if (it==d->streams.end() || it->second!=s) { return HP_ZT_MANAGED_STALE; }
        d->streams.erase(it); return HP_ZT_MANAGED_OK;
    } catch (...) { return HP_ZT_MANAGED_NATIVE; }
}

}
