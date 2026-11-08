// 0009 draft behavior test (N1): closed-port RST on hp (ZeroTier) netifs.
// Real pinned lwIP, every packet stays in memory on explicit test wires; no
// ZeroTier node, identity, host socket, SDK or download.
//
// Proves, against the real tcp_in.c/tcp_out.c no-listener path:
//  1. A bound connect() from an hp client netif to a closed port on an hp
//     peer netif fails fast with the RST error (lwIP ERR_RST surfaces as
//     errno ECONNRESET in lwIP's err.c table; this is lwIP's form of the
//     POSIX ECONNREFUSED a host stack reports for a refused connect).
//  2. The RST egresses the peer's own ingress netif only: an overlapping
//     same-subnet hp netif of another network never emits a byte (0008's
//     "no unbound RST may escape into another overlapping network" motive).
//  3. A disabled (hp_ready=0) or removed peer netif stays silent, keeping
//     0008's drain/teardown semantics.
#include "hp_zt_bound.h"
#include "lwip/sockets.h"
#include "lwip/tcpip.h"
#include "lwip/init.h"
#include "lwip/netif.h"
#include "lwip/ip.h"
#include "lwip/tcp.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <thread>
extern "C" {
int zts_errno=0;
struct netif* zts_lwip_hook_ip4_route_src(const ip4_addr_t*,const ip4_addr_t*) { return nullptr; }
const ip4_addr_t* zts_lwip_hook_etharp_get_gw(struct netif*,const ip4_addr_t*) { return nullptr; }
}
namespace {
int checks=0;
void check(bool value,const char* message) {
    if (!value) { std::cerr<<"FAIL: "<<message<<'\n'; std::abort(); }
    ++checks;
}
std::mutex ready_mutex; std::condition_variable ready_changed; bool ready=false;
void initialized(void*) { std::lock_guard<std::mutex> lock(ready_mutex); ready=true; ready_changed.notify_all(); }
struct Wire { struct netif* peer=nullptr; std::atomic<unsigned> packets{0}; char family='4',label='a'; };
struct netif client4={},peer4={},overlap4={},client6={},peer6={},overlap6={};
Wire client4_wire,peer4_wire,overlap4_wire,client6_wire,peer6_wire,overlap6_wire;
struct Delivery { struct pbuf* packet; struct netif* target; };
void deliver(void* arg) {
    auto* message=static_cast<Delivery*>(arg); ip_input(message->packet,message->target); delete message;
}
err_t forward(struct netif* n,struct pbuf* p) {
    auto* wire=static_cast<Wire*>(n->state); ++wire->packets;
    if (!wire->peer) { return ERR_OK; } // overlap sink: only counts would-be leaks.
    struct pbuf* copy=pbuf_clone(PBUF_RAW,PBUF_RAM,p);
    if (!copy) { return ERR_MEM; }
    auto* message=new Delivery{copy,wire->peer};
    const err_t result=tcpip_try_callback(deliver,message);
    if (result!=ERR_OK) { pbuf_free(copy); delete message; }
    return result;
}
err_t output4(struct netif* n,struct pbuf* p,const ip4_addr_t*) { return forward(n,p); }
err_t output6(struct netif* n,struct pbuf* p,const ip6_addr_t*) { return forward(n,p); }
err_t interface(struct netif* n) {
    auto* wire=static_cast<Wire*>(n->state);
    n->name[0]=wire->family; n->name[1]=wire->label; n->mtu=1500;
    n->output=output4; n->output_ip6=output6; n->flags=NETIF_FLAG_UP|NETIF_FLAG_LINK_UP;
    return ERR_OK;
}
unsigned added=0;
void wire_up(struct netif* a,Wire& aw,struct netif* b,Wire& bw) {
    aw.peer=b; bw.peer=a; aw.label=bw.label=static_cast<char>('a'+added++%26);
}
void add(struct netif* n,Wire& w,char family) {
    // Caller holds the lwIP core lock.
    w.family=family;
    ip4_addr_t any,zero; ip4_addr_set_any(&any); ip4_addr_set_zero(&zero);
    check(netif_add(n,&any,&any,&zero,&w,interface,tcpip_input)==n,"test netif added");
    netif_set_up(n); netif_set_link_up(n);
}
template<class F> void eventually(F predicate,const char* label) {
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
    while (!predicate()) {
        if (std::chrono::steady_clock::now()>=deadline) { check(false,label); }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    check(true,label);
}
int socket_error(int fd) {
    int error=-1; socklen_t size=sizeof(error);
    if (lwip_getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size)!=0) { return -1; }
    return error;
}
struct Attempt { int fd=-1; uint64_t network=0,epoch=0; };
Attempt attempt(const char* destination,uint16_t port,uint64_t network,bool six) {
    Attempt a; a.network=network;
    uint8_t ip[16]={};
    check(lwip_inet_pton(six?AF_INET6:AF_INET,destination,ip)==1,"closed port destination parsed");
    int result=hp_zt_bound_open(network,ip,six?16:4,port,&a.fd,&a.epoch);
    check((result==HP_ZT_BOUND_OK||result==HP_ZT_BOUND_AGAIN)&&a.fd>=0&&a.epoch,"bound connect to closed port started");
    return a;
}
void refused_fast(const char* destination,uint16_t port,uint64_t network,bool six,Wire& peer_wire,Wire& overlap_wire) {
    const unsigned peer_before=peer_wire.packets.load(),overlap_before=overlap_wire.packets.load();
    auto a=attempt(destination,port,network,six);
    const auto start=std::chrono::steady_clock::now();
    int error=0;
    eventually([&]{ const int e=socket_error(a.fd); if (e!=0&&e!=EINPROGRESS&&e!=EALREADY&&e!=EWOULDBLOCK) { error=e; return true; } return false; },
        "closed port connect fails fast (peer RST observed)");
    const std::chrono::milliseconds elapsed=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start);
    std::cerr<<"  observed SO_ERROR="<<error<<" after "<<elapsed.count()<<"ms\n";
    const bool is_refused_errno = (error==104 /* lwIP ECONNRESET */ || error==ECONNRESET ||
                                   error==111 /* lwIP ECONNREFUSED */ || error==ECONNREFUSED);
    check(is_refused_errno,"closed port errno is lwIP ERR_RST (ECONNRESET/104; lwIP's POSIX ECONNREFUSED equivalent)");
    check(elapsed<std::chrono::milliseconds(1500),"refused within a sub-second RST round trip, not a timeout");
    check(peer_wire.packets.load()>peer_before,"peer hp netif emitted the RST itself");
    check(overlap_wire.packets.load()==overlap_before,"overlapping other-network netif emitted nothing");
    check(hp_zt_bound_state(a.fd,a.network,a.epoch)==HP_ZT_BOUND_ERROR,"boundary state reports dead stream");
    uint8_t data[8]={}; uint32_t count=99;
    check(hp_zt_bound_read(a.fd,data,8,&count)==HP_ZT_BOUND_ERROR&&!count,"boundary read reports the refusal");
    check(lwip_close(a.fd)==0,"refused socket closed");
    std::cerr<<"  refused "<<destination<<":"<<port<<" errno="<<error<<" in "<<elapsed.count()<<"ms, peer RSTs="
             <<(peer_wire.packets.load()-peer_before)<<", overlap leaks="
             <<(overlap_wire.packets.load()-overlap_before)<<'\n';
}
void stays_silent(const char* destination,uint16_t port,uint64_t network,bool six,Wire& peer_wire,const char* label) {
    const unsigned before=peer_wire.packets.load();
    auto a=attempt(destination,port,network,six);
    std::this_thread::sleep_for(std::chrono::milliseconds(400));
    check(peer_wire.packets.load()==before,label);
    const int error=socket_error(a.fd);
    check(error==EINPROGRESS||error==EALREADY||error==EWOULDBLOCK||error==0,"no RST reached the client");
    check(lwip_close(a.fd)==0,"silent-path socket closed");
}
}
int main() {
    std::cerr<<"phase: isolated tcpip init\n";
    tcpip_init(initialized,nullptr);
    { std::unique_lock<std::mutex> lock(ready_mutex);check(ready_changed.wait_for(lock,std::chrono::seconds(3),[]{return ready;}),"isolated lwIP init"); }
    wire_up(&client4,client4_wire,&peer4,peer4_wire);
    wire_up(&client6,client6_wire,&peer6,peer6_wire);
    LOCK_TCPIP_CORE();
    add(&client4,client4_wire,'4'); add(&peer4,peer4_wire,'4'); add(&overlap4,overlap4_wire,'4');
    add(&client6,client6_wire,'6'); add(&peer6,peer6_wire,'6'); add(&overlap6,overlap6_wire,'6');
    ip4_addr_t ca,pa,oa,mask,zero; ip4_addr_set_zero(&zero);
    ip4addr_aton("10.9.9.2",&ca); ip4addr_aton("10.9.9.3",&pa); ip4addr_aton("10.9.9.4",&oa);
    ip4addr_aton("255.255.255.0",&mask);
    netif_set_addr(&client4,&ca,&mask,&zero); netif_set_addr(&peer4,&pa,&mask,&zero); netif_set_addr(&overlap4,&oa,&mask,&zero);
    client4.hp_network=200; client4.hp_generation=20; client4.hp_ready=1; client4.hp_prefix6=0; client4.hp_route_count=0;
    peer4.hp_network=201; peer4.hp_generation=21; peer4.hp_ready=1; peer4.hp_prefix6=0; peer4.hp_route_count=0;
    overlap4.hp_network=202; overlap4.hp_generation=22; overlap4.hp_ready=1; overlap4.hp_prefix6=0; overlap4.hp_route_count=0;
    ip6_addr_t c6,p6,o6; ip6addr_aton("fd81:9::2",&c6); ip6addr_aton("fd81:9::3",&p6); ip6addr_aton("fd81:9::4",&o6);
    netif_ip6_addr_set(&client6,0,&c6); netif_ip6_addr_set_state(&client6,0,IP6_ADDR_PREFERRED);
    netif_ip6_addr_set(&peer6,0,&p6); netif_ip6_addr_set_state(&peer6,0,IP6_ADDR_PREFERRED);
    netif_ip6_addr_set(&overlap6,0,&o6); netif_ip6_addr_set_state(&overlap6,0,IP6_ADDR_PREFERRED);
    std::memcpy(client6.hp_source6,c6.addr,16); std::memcpy(peer6.hp_source6,p6.addr,16); std::memcpy(overlap6.hp_source6,o6.addr,16);
    client6.hp_network=204; client6.hp_generation=24; client6.hp_ready=1; client6.hp_prefix6=64; client6.hp_route_count=0;
    peer6.hp_network=205; peer6.hp_generation=25; peer6.hp_ready=1; peer6.hp_prefix6=64; peer6.hp_route_count=0;
    overlap6.hp_network=206; overlap6.hp_generation=26; overlap6.hp_ready=1; overlap6.hp_prefix6=64; overlap6.hp_route_count=0;
    UNLOCK_TCPIP_CORE();
    std::cerr<<"phase: IPv4 closed-port refusal\n"; refused_fast("10.9.9.3",2291,200,false,peer4_wire,overlap4_wire);
    std::cerr<<"phase: IPv6 closed-port refusal\n"; refused_fast("fd81:9::3",2293,204,true,peer6_wire,overlap6_wire);
    std::cerr<<"phase: disabled hp netif drain silence\n";
    LOCK_TCPIP_CORE(); peer4.hp_ready=0; UNLOCK_TCPIP_CORE();
    stays_silent("10.9.9.3",2295,200,false,peer4_wire,"hp_ready=0 peer answers no RST (drain silence)");
    LOCK_TCPIP_CORE(); peer4.hp_ready=1; UNLOCK_TCPIP_CORE();
    std::cerr<<"phase: removed hp netif teardown silence\n";
    LOCK_TCPIP_CORE(); peer4.hp_ready=0; netif_remove(&peer4); UNLOCK_TCPIP_CORE();
    stays_silent("10.9.9.3",2299,200,false,peer4_wire,"removed peer answers no RST (teardown silence)");
    std::cout<<"PASS: "<<checks<<" real lwIP in-memory checks; closed-port RST on hp netifs fails fast (ERR_RST/ECONNRESET), "
               "RST confined to the ingress netif, drain/teardown silence; no ZeroTier node, identity or host socket\n";
}
