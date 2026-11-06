#include "HpEventProjection.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <climits>
#include <iostream>
struct Guarded {
    std::array<unsigned char,64> before;
    zts_net_info_t event;
    std::array<unsigned char,64> after;
};
int main() {
    ZT_VirtualNetworkConfig config{};
    Guarded guarded{};
    guarded.before.fill(0xa5);guarded.after.fill(0x5a);
    auto convert=[](zts_sockaddr_storage* out,const sockaddr_storage* in){std::memcpy(out,in,std::min(sizeof(*out),sizeof(*in)));};
    config.nwid=0x1234;
    std::memset(config.name,'x',sizeof(config.name));
    for(unsigned int n : {0u,32u,128u,UINT_MAX}) {
        config.assignedAddressCount=n;config.routeCount=n;config.multicastSubscriptionCount=n;
        ZeroTier::hp_project_network(guarded.event,config,convert);
        assert(guarded.event.net_id==0x1234);
        assert(guarded.event.assigned_addr_count==std::min(n,16u));
        assert(guarded.event.route_count==std::min(n,32u));
        assert(guarded.event.multicast_sub_count==std::min(n,1024u));
        assert(guarded.event.name[sizeof(guarded.event.name)-1]==0);
        for(auto b:guarded.before){assert(b==0xa5);}
        for(auto b:guarded.after){assert(b==0x5a);}
    }
    static_assert(sizeof(config.assignedAddresses)/sizeof(config.assignedAddresses[0])==32,"fixed source changed");
    static_assert(sizeof(config.routes)/sizeof(config.routes[0])==128,"fixed source changed");
    // The similarly named NETWORK_MULTICAST constant is not this array's bound.
    static_assert(sizeof(config.multicastSubscriptions)/sizeof(config.multicastSubscriptions[0])==1024,"fixed source changed");
    std::cout << "real network projection: core32/address16, core128/route32, multicast1024, UINT_MAX, NUL and canaries passed\n";
}
