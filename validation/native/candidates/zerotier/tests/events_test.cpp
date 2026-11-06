#include "Events.hpp"
#include "HpEventOwnership.hpp"
#include <type_traits>
#include "NodeService.hpp"
#include <cassert>
#include <array>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <iostream>
namespace ZeroTier {
NodeService* zts_service=nullptr; // The real Events TU only queries this unused boundary.
HpWorkers hp_workers;
int NodeService::isRunning() const {return 0;}
extern void (*_userEventCallback)(void*);
}
extern "C" void zts_util_delay(unsigned long milliseconds) {std::this_thread::sleep_for(std::chrono::milliseconds(milliseconds));}
using namespace ZeroTier;
namespace {
Events* events;
std::array<uint8_t,32> source;
std::mutex mutex;
std::condition_variable changed;
bool entered=false,released=false;
int received=0;
int capacity_received=0;
int rejected_deletes=0,success_deletes=0,address_received=0;
struct CountAddressDelete {
    int* count;
    template<class T> void operator()(T* object) const {
        assert((std::is_same<T,zts_addr_info_t>::value));
        ++*count;delete object;
    }
};
const unsigned int address_codes[]={ZTS_EVENT_ADDR_ADDED_IP4,ZTS_EVENT_ADDR_ADDED_IP6,ZTS_EVENT_ADDR_REMOVED_IP4,ZTS_EVENT_ADDR_REMOVED_IP6};
void rejected_addresses() {
    for(auto code:address_codes) {
        auto* address=new zts_addr_info_t();
        HpEventOwner<CountAddressDelete> owner(code,address,CountAddressDelete{&rejected_deletes});
        assert(!events->enqueue(code,address,0));
    }
}
void address_callback(void* raw) {
    auto* message=static_cast<zts_event_msg_t*>(raw);
    assert(hp_event_input_is_owned(message->event_code) && message->addr);
    if(++address_received==4){events->disable();events->clrState(ZTS_STATE_CALLBACKS_RUNNING);}
}
void capacity_callback(void* raw) {
    auto* message=static_cast<zts_event_msg_t*>(raw);
    assert(message->event_code==ZTS_EVENT_STORE_IDENTITY_PUBLIC && message->len==32);
    ++capacity_received;
    if(capacity_received==1) {
        assert(events->enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,source.data(),source.size()));
        assert(!events->enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,source.data(),source.size()));
        events->disable();events->clrState(ZTS_STATE_CALLBACKS_RUNNING);
    }
}
void callback(void* raw) {
    auto* message=static_cast<zts_event_msg_t*>(raw);
    assert(Events::isCallbackThread());
    if(message->event_code==ZTS_EVENT_STORE_IDENTITY_SECRET) {
        assert(message->len==32 && message->cache!=source.data());
        auto* data=static_cast<const uint8_t*>(message->cache);
        for(int i=0;i<32;++i){assert(data[i]==0x11);}
        std::array<uint8_t,8> next{};next.fill(0x33);
        assert(events->enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,next.data(),next.size()));
        next.fill(0x44); // Callback reentry cannot deadlock the producer gate.
        std::unique_lock<std::mutex> lock(mutex);entered=true;changed.notify_all();
        changed.wait(lock,[]{return released;});
    } else {
        assert(message->event_code==ZTS_EVENT_STORE_IDENTITY_PUBLIC && message->len==8);
        auto* data=static_cast<const uint8_t*>(message->cache);
        for(int i=0;i<8;++i){assert(data[i]==0x33);}
    }
    ++received;
}
}
int main() {
    Events owned;events=&owned;_userEventCallback=callback;
    owned.enable();owned.setState(ZTS_STATE_CALLBACKS_RUNNING);
    source.fill(0x11);
    assert(owned.enqueue(ZTS_EVENT_STORE_IDENTITY_SECRET,source.data(),source.size()));
    source.fill(0x22);
    std::array<uint8_t,ZTS_STORE_DATA_LEN+1> oversized{};
    assert(!owned.enqueue(ZTS_EVENT_STORE_IDENTITY_SECRET,oversized.data(),oversized.size()));
    assert(!owned.enqueue(ZTS_EVENT_STORE_IDENTITY_SECRET,nullptr,1));
    assert(!owned.enqueue(ZTS_EVENT_STORE_IDENTITY_SECRET,source.data(),-1));
    assert(hp_workers.begin(HpWorkers::Callback));
    std::thread worker([&]{owned.run();hp_workers.finish(HpWorkers::Callback);});
    {std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[]{return entered;});}
    owned.disable();owned.clrState(ZTS_STATE_CALLBACKS_RUNNING);
    assert(!hp_workers.wait_node(std::chrono::steady_clock::now()+std::chrono::milliseconds(10)));
    assert(!owned.enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,source.data(),source.size()));
    {std::lock_guard<std::mutex> lock(mutex);released=true;changed.notify_all();}
    worker.join();assert(received==2);
    assert(hp_workers.wait_node(std::chrono::steady_clock::now()+std::chrono::milliseconds(10)));
    assert(!Events::isCallbackThread());
    rejected_addresses();assert(rejected_deletes==4); // Disabled queue.
    {HpEventOwner<CountAddressDelete> borrowed(ZTS_EVENT_STORE_IDENTITY_SECRET,source.data(),CountAddressDelete{&rejected_deletes});}
    assert(rejected_deletes==4);
    _userEventCallback=capacity_callback;owned.enable();owned.setState(ZTS_STATE_CALLBACKS_RUNNING);
    for(int i=0;i<1024;++i){assert(owned.enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,source.data(),source.size()));}
    assert(!owned.enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,source.data(),source.size()));
    rejected_addresses();assert(rejected_deletes==8); // Full queue.
    owned.run();assert(capacity_received==1025);
    assert(!owned.enqueue(ZTS_EVENT_STORE_IDENTITY_PUBLIC,source.data(),source.size()));
    _userEventCallback=address_callback;owned.enable();owned.setState(ZTS_STATE_CALLBACKS_RUNNING);
    for(auto code:address_codes) {
        auto* address=new zts_addr_info_t();
        HpEventOwner<CountAddressDelete> owner(code,address,CountAddressDelete{&success_deletes});
        assert(owned.enqueue(code,address,0));owner.transfer();
    }
    assert(success_deletes==0);owned.run();assert(address_received==4 && success_deletes==0);
    owned.clrCallback();
    std::cout << "actual Events TU offline: borrowed cache copied, callback reentry, blocked callback retains worker, exact1024 queue/refill, typed address rejection/transfer, borrowed-cache ownership and final queue drain passed\n";
}
