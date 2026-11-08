// Actual VirtualTap address remove/re-add; no NodeService/Node or identity.
// Route checks assert the production path directly: init_interface promotes
// managed IPv6 addresses past DAD itself, so no manual PREFERRED injection.
#include "InetAddress.hpp"
#include "MAC.hpp"
#include "Mutex.hpp"
#include "VirtualTap.hpp"
#include "HpLifecycle.hpp"
#include "Events.hpp"
#include "hp_zt_bound.h"
#include "lwip/netif.h"
#include "lwip/tcpip.h"
#include <condition_variable>
#include <chrono>
#include <mutex>
#include <iostream>
#include <cstdlib>
#include <cstring>
namespace ZeroTier { Events* zts_events=nullptr; HpWorkers hp_workers; }
extern "C" { int zts_errno=0; }
namespace {
std::mutex mutex;std::condition_variable changed;bool ready=false;unsigned checks=0;
void check(bool b,const char* text) { if (!b) { std::cerr<<"FAIL: "<<text<<'\n';std::abort(); }++checks; }
void initialized(void*) { std::lock_guard<std::mutex> lock(mutex);ready=true;changed.notify_all(); }
void discard(void*,void*,uint64_t,const ZeroTier::MAC&,const ZeroTier::MAC&,unsigned,unsigned,const void*,unsigned) {}
}
int main() {
    tcpip_init(initialized,nullptr);
    { std::unique_lock<std::mutex> lock(mutex);check(changed.wait_for(lock,std::chrono::seconds(3),[]{return ready;}),"isolated stack initialized"); }
    uint8_t a[16]={0xfd,0,0,1},b[16]={0xfd,0,0,2},destination[16]={0xfd,0,0,1};
    a[15]=1;b[15]=1;destination[15]=2;
    {
        ZeroTier::VirtualTap tap("",ZeroTier::MAC(0x10203040506ULL),1500,0,900,discard,nullptr);
        const ZeroTier::InetAddress first(a,16,64),second(b,16,64);
        check(tap.addIp(first),"actual add first address");tap.hpConfigure(true);
        auto* original=static_cast<struct netif*>(tap.netif6);uint64_t epoch=0;
        ip_addr_t dest,source;ip_addr_set_zero_ip6(&dest);std::memcpy(ip_2_ip6(&dest)->addr,destination,16);
        LOCK_TCPIP_CORE();epoch=original->hp_generation;
        check(hp_zt_route_locked(900,&dest,&source)==original,"actual first route usable");UNLOCK_TCPIP_CORE();
        tap.hpConfigure(false);check(tap.removeIp(first),"actual remove first address");
        check(tap.addIp(second),"actual add replacement IPv6");tap.hpConfigure(true);
        auto* replacement=static_cast<struct netif*>(tap.netif6);
        LOCK_TCPIP_CORE();
        check(replacement->state==&tap && replacement->hp_generation && replacement->hp_generation!=epoch,"replacement registered with new epoch");
        check(!hp_zt_route_locked(900,&dest,&source),"old IPv6 prefix never rebinds");
        std::memcpy(ip_2_ip6(&dest)->addr,b,16);reinterpret_cast<uint8_t*>(ip_2_ip6(&dest)->addr)[15]=2;
        check(hp_zt_route_locked(900,&dest,&source)==replacement,"actual remove/add restores new IPv6 route");
        UNLOCK_TCPIP_CORE();
    }
    std::cout<<"PASS: "<<checks<<" actual VirtualTap IPv6 remove/re-add checks; local pipe/poll thread and isolated lwIP only, no ZeroTier node/identity/socket\n";
}
