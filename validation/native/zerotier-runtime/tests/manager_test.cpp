// Real manager, synthetic C engine only. No node, network or identity file.
#include "hp_zt_manager.h"
#include "ZeroTierSockets.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

namespace {
struct Gate {
    std::mutex mutex; std::condition_variable cv; bool armed=false,entered=false,released=false;
    void arm() { std::lock_guard<std::mutex> lock(mutex); armed=true; entered=false; released=false; }
    void block() { std::unique_lock<std::mutex> lock(mutex); if (!armed) return; entered=true; cv.notify_all(); cv.wait(lock,[this]{return released;}); armed=false; }
    void wait() { std::unique_lock<std::mutex> lock(mutex); if (!cv.wait_for(lock,std::chrono::seconds(3),[this]{return entered;})) std::abort(); }
    void open() { std::lock_guard<std::mutex> lock(mutex); released=true; cv.notify_all(); }
};
Gate validate_gate,quiet_gate,start_gate,online_gate,join_gate;
std::atomic<int> starts{0},joins{0},leaves{0},stops{0},validations{0},inits{0};
std::atomic<int> native_stop{HP_ZT_OK}, native_join{ZTS_ERR_OK}, native_start{ZTS_ERR_OK}, native_init{ZTS_ERR_OK};
std::atomic<bool> quiet{true}, stop_quiet{true};
std::atomic<uint64_t> node_id{0x123456789aULL};
std::atomic<int> network_status{1};
constexpr uint64_t public_id=0x123456789aULL;
uint8_t identity[HP_ZT_IDENTITY_BYTES]={};
int checks=0;
void check(bool b,const char* label) { if(!b) { std::cerr<<"FAIL: "<<label<<"\n"; std::exit(1); } ++checks; }
uint64_t create() { uint64_t owner=0; check(hp_zt_device_new(identity,sizeof(identity),1000,&owner)==HP_ZT_MANAGED_OK && owner,"device new"); return owner; }
void finish(uint64_t owner) { check(hp_zt_device_stop(owner,1000)==HP_ZT_MANAGED_OK,"device stop"); check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_OK,"device release"); }
void start(uint64_t owner) { check(hp_zt_device_start(owner,1000)==HP_ZT_MANAGED_OK,"device start"); }
}
extern "C" {
int hp_zt_identity_validate(const uint8_t *data,size_t len,uint64_t *id) { ++validations; validate_gate.block(); *id=(data && len==sizeof(identity)) ? public_id : 0; return *id ? HP_ZT_OK : HP_ZT_IDENTITY_INVALID; }
int hp_zt_node_quiescent() { quiet_gate.block(); return quiet.load() ? 1 : 0; }
int hp_zt_node_stop(uint32_t) { ++stops; int value=native_stop.load(); if(value==HP_ZT_OK && stop_quiet.load()) quiet=true; return value; }
int zts_init_from_memory(const char*,unsigned int) { ++inits; quiet=false; return native_init.load(); }
int zts_init_allow_id_cache(unsigned int) { return ZTS_ERR_OK; }
int zts_init_allow_net_cache(unsigned int) { return ZTS_ERR_OK; }
int zts_init_allow_peer_cache(unsigned int) { return ZTS_ERR_OK; }
int zts_init_allow_roots_cache(unsigned int) { return ZTS_ERR_OK; }
int zts_node_start() { ++starts; start_gate.block(); return native_start.load(); }
int zts_node_is_online() { online_gate.block(); return 1; }
uint64_t zts_node_get_id() { return node_id.load(); }
int zts_net_join(uint64_t) { ++joins; join_gate.block(); return native_join.load(); }
int zts_net_leave(uint64_t) { ++leaves; return ZTS_ERR_OK; }
int zts_net_get_status(uint64_t) { return network_status.load(); }
}
static void normal_cases() {
    uint64_t invalid=99; check(hp_zt_device_new(identity,3,100,&invalid)==HP_ZT_MANAGED_ARGUMENT && invalid==0,"bad identity argument clears output");
    quiet=false; int before_stop=stops.load(); uint64_t foreign=0;
    check(hp_zt_device_new(identity,sizeof(identity),1000,&foreign)==HP_ZT_MANAGED_BUSY && foreign,"foreign raw node not adopted");
    check(hp_zt_device_stop(foreign,1000)==HP_ZT_MANAGED_OK && stops.load()==before_stop,"foreign raw node not stopped");
    check(hp_zt_device_release(foreign,1000)==HP_ZT_MANAGED_OK && !quiet.load(),"foreign raw node remains owned externally"); quiet=true;
    native_init=-1; uint64_t failed_owner=0;
    check(hp_zt_device_new(identity,sizeof(identity),1000,&failed_owner)==HP_ZT_MANAGED_NATIVE && failed_owner,"failed init retains an owner");
    check(hp_zt_device_release(failed_owner,1000)==HP_ZT_MANAGED_BUSY,"failed init cannot release vault");
    native_stop=HP_ZT_UNAVAILABLE; check(hp_zt_device_stop(failed_owner,1000)==HP_ZT_MANAGED_NATIVE,"failed stop surfaced");
    check(hp_zt_device_release(failed_owner,1000)==HP_ZT_MANAGED_BUSY,"failed stop cannot release vault");
    native_init=ZTS_ERR_OK; native_stop=HP_ZT_OK; finish(failed_owner);
    uint64_t owner=create(); start(owner); uint64_t rejected=1;
    check(hp_zt_device_new(identity,sizeof(identity),100,&rejected)==HP_ZT_MANAGED_BUSY && rejected==0,"single device owner");
    node_id=public_id+1; uint64_t wrong_id_lease=1;
    check(hp_zt_network_join(owner,10,1000,&wrong_id_lease)==HP_ZT_MANAGED_NOT_ONLINE && wrong_id_lease==0,"foreign runtime identity cannot admit network"); node_id=public_id;
    uint64_t a=0,b=0,c=0; int start_join=joins.load(),start_leave=leaves.load();
    check(hp_zt_network_join(owner,10,1000,&a)==0 && a,"first join");
    check(hp_zt_network_join(owner,10,1000,&b)==0 && b && b!=a && joins.load()==start_join+1,"same network shares engine join");
    check(hp_zt_network_join(owner,20,1000,&c)==0 && joins.load()==start_join+2,"different network joins independently");
    check(hp_zt_network_leave(owner,a,1000)==0 && leaves.load()==start_leave,"first same-network leave does not disconnect");
    uint32_t phase=0,online=0;
    check(hp_zt_network_status(owner,b,1000,&phase,&online)==0 && phase==HP_ZT_NETWORK_CONFIGURED && online,"remaining lease stays active");
    network_status=6; check(hp_zt_network_status(owner,b,1000,&phase,&online)==0 && phase==HP_ZT_NETWORK_AUTH_REQUIRED,"authorization required not presented configured"); network_status=1;
    check(hp_zt_network_leave(owner,b,1000)==0 && leaves.load()==start_leave+1,"last same-network lease leaves once");
    check(hp_zt_network_status(owner,c,1000,&phase,&online)==0 && online,"other network remains active");
    check(hp_zt_network_leave(owner,b,1000)==HP_ZT_MANAGED_STALE,"old network lease rejected");
    check(hp_zt_network_leave(owner+100,c,1000)==HP_ZT_MANAGED_STALE,"wrong owner rejected");
    uint64_t leases[31]={}; for (int i=0;i<31;++i) check(hp_zt_network_join(owner,100+i,1000,&leases[i])==0 && leases[i],"capacity admission");
    uint64_t overflow=99; check(hp_zt_network_join(owner,999,1000,&overflow)==HP_ZT_MANAGED_CAPACITY && overflow==0,"32 lease capacity");
    native_stop=HP_ZT_TIMEOUT; check(hp_zt_device_stop(owner,1000)==HP_ZT_MANAGED_TIMEOUT,"native timeout retained");
    check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_BUSY,"timeout cannot release owner");
    native_stop=HP_ZT_OK; stop_quiet=false;
    check(hp_zt_device_stop(owner,1000)==HP_ZT_MANAGED_NATIVE,"success without native quiescence rejected");
    check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_BUSY,"unproven quiescence cannot release owner");
    stop_quiet=true; finish(owner);
    check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_STALE,"released owner cannot be replayed");
    uint64_t next=create(); check(next!=owner,"owner not reused");
    check(hp_zt_network_leave(next,c,1000)==HP_ZT_MANAGED_STALE,"old lease rejected by new owner"); finish(next);
}
static void blocked_cases() {
    validate_gate.arm(); uint64_t delayed=9; int result=-1;
    std::thread validator([&]{result=hp_zt_device_new(identity,sizeof(identity),20,&delayed);}); validate_gate.wait();
    check(hp_zt_device_stop(1,20)==HP_ZT_MANAGED_STALE,"no published owner while identity validation blocked");
    std::this_thread::sleep_for(std::chrono::milliseconds(35)); validate_gate.open(); validator.join();
    check(result==HP_ZT_MANAGED_TIMEOUT && delayed==0,"late identity validation returns timeout without engine touch");
    quiet_gate.arm(); uint64_t pending=0; int pending_result=-1; int prior_inits=inits.load();
    std::thread preparing([&]{pending_result=hp_zt_device_new(identity,sizeof(identity),1000,&pending);}); quiet_gate.wait();
    check(pending!=0,"reservation exists before raw-node quiescence check returns");
    check(hp_zt_device_stop(pending,20)==HP_ZT_MANAGED_TIMEOUT,"stop fences pre-init check and waits");
    quiet_gate.open(); preparing.join();
    check(pending_result==HP_ZT_MANAGED_CLOSING && inits.load()==prior_inits,"pre-init stop fence prevents native identity init");
    finish(pending);
    quiet_gate.arm(); pending=0; pending_result=-1; prior_inits=inits.load();
    std::thread late_prepare([&]{pending_result=hp_zt_device_new(identity,sizeof(identity),20,&pending);}); quiet_gate.wait();
    std::this_thread::sleep_for(std::chrono::milliseconds(35)); quiet_gate.open(); late_prepare.join();
    check(pending_result==HP_ZT_MANAGED_TIMEOUT && pending && inits.load()==prior_inits,"expired pre-init check cannot start native identity init");
    finish(pending);
    uint64_t owner=create(); start_gate.arm(); int start_result=-1;
    std::thread worker([&]{start_result=hp_zt_device_start(owner,1000);}); start_gate.wait();
    check(hp_zt_device_stop(owner,20)==HP_ZT_MANAGED_TIMEOUT,"stop cannot pretend blocked start retired");
    check(hp_zt_device_release(owner,20)==HP_ZT_MANAGED_TIMEOUT,"blocked start retains owner");
    start_gate.open(); worker.join(); check(start_result==HP_ZT_MANAGED_CLOSING,"late start result rejected"); finish(owner);
    owner=create(); start(owner); join_gate.arm(); uint64_t lease=0; int join_result=-1;
    std::thread joiner([&]{join_result=hp_zt_network_join(owner,12,1000,&lease);}); join_gate.wait();
    check(hp_zt_device_stop(owner,20)==HP_ZT_MANAGED_TIMEOUT,"stop waits admitted join");
    check(hp_zt_device_release(owner,20)==HP_ZT_MANAGED_TIMEOUT,"blocked join retains owner");
    join_gate.open(); joiner.join(); check(join_result==HP_ZT_MANAGED_CLOSING && lease,"late join preserves admission for stop"); finish(owner);
    owner=create(); native_start=-1; int attempts=starts.load();
    check(hp_zt_device_start(owner,1000)==HP_ZT_MANAGED_NATIVE,"failed start surfaced");
    check(hp_zt_device_start(owner,1000)==HP_ZT_MANAGED_CLOSING && starts.load()==attempts+1,"failed start not replayed");
    native_start=ZTS_ERR_OK; finish(owner);
    owner=create(); start(owner); native_join=-1; lease=0;
    check(hp_zt_network_join(owner,15,1000,&lease)==HP_ZT_MANAGED_NATIVE && lease,"failed join retains lease"); native_join=ZTS_ERR_OK;
    check(hp_zt_network_leave(owner,lease,1000)==HP_ZT_MANAGED_OK,"failed join explicitly retired"); finish(owner);
    owner=create(); quiet_gate.arm(); int stop_result=-1;
    std::thread late_stop([&]{stop_result=hp_zt_device_stop(owner,20);}); quiet_gate.wait();
    std::this_thread::sleep_for(std::chrono::milliseconds(35)); quiet_gate.open(); late_stop.join();
    check(stop_result==HP_ZT_MANAGED_TIMEOUT,"late quiescence retains original stop ownership");
    check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_BUSY,"late stop is not an implicit retirement acknowledgement");
    check(hp_zt_device_stop(owner,1000)==HP_ZT_MANAGED_OK,"explicit stop retry confirms original retirement");
    quiet_gate.arm(); int release_result=-1;
    std::thread late_release([&]{release_result=hp_zt_device_release(owner,20);}); quiet_gate.wait();
    std::this_thread::sleep_for(std::chrono::milliseconds(35)); quiet_gate.open(); late_release.join();
    check(release_result==HP_ZT_MANAGED_TIMEOUT,"late release query must retain owner");
    uint64_t blocked_owner=1;
    check(hp_zt_device_new(identity,sizeof(identity),1000,&blocked_owner)==HP_ZT_MANAGED_BUSY && blocked_owner==0,"release timeout cannot admit a replacement owner");
    check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_OK,"explicit exact owner release retry");
}
static void online_fence() {
    uint64_t owner=create(); start(owner); online_gate.arm(); uint64_t lease=0; int result=-1; int before=joins.load();
    std::thread joiner([&]{result=hp_zt_network_join(owner,42,1000,&lease);}); online_gate.wait();
    check(hp_zt_device_stop(owner,20)==HP_ZT_MANAGED_TIMEOUT,"stop fenced while online call blocked");
    online_gate.open(); joiner.join();
    check(result==HP_ZT_MANAGED_CLOSING && joins.load()==before && lease==0,"no new native join after closing fence");
    finish(owner);
}
int main(int argc,char** argv) {
    if(argc==2 && std::string(argv[1])=="online-fence") online_fence();
    else { normal_cases(); blocked_cases(); }
    std::cout<<"PASS: "<<checks<<" manager checks; synthetic engine, no node/network\n";
}
