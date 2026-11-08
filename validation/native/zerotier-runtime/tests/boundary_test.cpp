// Real pinned lwIP/route/socket code. All packets stay in memory; no ZT node,
// identity, host socket or overlay. The only thread is lwIP's tcpip worker.
#include "hp_zt_bound.h"
#include "lwip/sockets.h"
#include "lwip/tcpip.h"
#include "lwip/init.h"
#include "lwip/netif.h"
#include "lwip/ip4.h"
#include "lwip/ip.h"
#include "lwip/ip6.h"
#include "lwip/tcp.h"
#include "lwip/priv/tcp_priv.h"
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
std::mutex ready_mutex;
std::condition_variable ready_changed;
bool ready=false;
void initialized(void*) { std::lock_guard<std::mutex> lock(ready_mutex); ready=true; ready_changed.notify_all(); }
struct Wire {
    struct netif* peer=nullptr;
    std::atomic<unsigned> packets{0};
    std::atomic<bool> drop{false};
    char family='4', label='a';
};
struct netif clients[4]={},servers[4]={};
Wire client_wire[4],server_wire[4];
struct Delivery { struct pbuf* packet; struct netif* target; };
void deliver(void* arg) {
    auto* message=static_cast<Delivery*>(arg);
    ip_input(message->packet,message->target); delete message;
}
err_t forward(struct netif* n,struct pbuf* p) {
    auto* wire=static_cast<Wire*>(n->state);++wire->packets;
    if (wire->drop.load()) { return ERR_OK; }
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
    n->name[0]=wire->family;n->name[1]=wire->label;n->mtu=1500;
    n->output=output4;n->output_ip6=output6;
    n->flags=NETIF_FLAG_UP|NETIF_FLAG_LINK_UP;
    return ERR_OK;
}
void setup(unsigned i,bool six) {
    auto& c=clients[i];auto& s=servers[i];auto& cw=client_wire[i];auto& sw=server_wire[i];
    cw.peer=&s;sw.peer=&c;cw.family=six?'6':'4';sw.family='r';
    cw.label=static_cast<char>('a'+i);sw.label=static_cast<char>('a'+i);
    ip4_addr_t ca,sa,mask,gw;ip4addr_aton(six?"0.0.0.0":"10.1.2.2",&ca);
    ip4addr_aton(six?"0.0.0.0":"10.1.2.3",&sa);ip4addr_aton("255.255.255.0",&mask);ip4_addr_set_zero(&gw);
    LOCK_TCPIP_CORE();
    check(netif_add(&c,&ca,&mask,&gw,&cw,interface,tcpip_input)==&c,"add client netif");
    check(netif_add(&s,&sa,&mask,&gw,&sw,interface,tcpip_input)==&s,"add server netif");
    c.hp_network=100+i;c.hp_generation=10+i;c.hp_ready=1;c.hp_prefix6=six?64:0;c.hp_route_count=0;
    s.hp_network=0;s.hp_generation=100+i;s.hp_ready=1;s.hp_prefix6=six?64:0;s.hp_route_count=0;
    if (six) {
        ip6_addr_t a,b;ip6addr_aton("fd80:1::2",&a);ip6addr_aton("fd80:1::3",&b);
        std::memcpy(c.hp_source6,a.addr,16);std::memcpy(s.hp_source6,b.addr,16);
        netif_ip6_addr_set(&c,0,&a);netif_ip6_addr_set_state(&c,0,IP6_ADDR_PREFERRED);
        netif_ip6_addr_set(&s,0,&b);netif_ip6_addr_set_state(&s,0,IP6_ADDR_PREFERRED);
    }
    netif_set_up(&c);netif_set_link_up(&c);netif_set_up(&s);netif_set_link_up(&s);
    UNLOCK_TCPIP_CORE();
}
int listening(unsigned i,bool six,uint16_t port) {
    int fd=lwip_socket(six?AF_INET6:AF_INET,SOCK_STREAM,IPPROTO_TCP);check(fd>=0,"server lwIP socket");
    struct ifreq iface={};
    LOCK_TCPIP_CORE();check(netif_index_to_name(netif_get_index(&servers[i]),iface.ifr_name)!=nullptr,"exact netif name");UNLOCK_TCPIP_CORE();
    check(lwip_setsockopt(fd,SOL_SOCKET,SO_BINDTODEVICE,&iface,sizeof(iface))==0,"server bound to original netif");
    if (six) {
        struct sockaddr_in6 addr={};addr.sin6_len=sizeof(addr);addr.sin6_family=AF_INET6;addr.sin6_port=lwip_htons(port);
        lwip_inet_pton(AF_INET6,"fd80:1::3",&addr.sin6_addr);
        check(lwip_bind(fd,reinterpret_cast<struct sockaddr*>(&addr),sizeof(addr))==0,"server IPv6 bind");
    } else {
        struct sockaddr_in addr={};addr.sin_len=sizeof(addr);addr.sin_family=AF_INET;addr.sin_port=lwip_htons(port);
        lwip_inet_pton(AF_INET,"10.1.2.3",&addr.sin_addr);
        check(lwip_bind(fd,reinterpret_cast<struct sockaddr*>(&addr),sizeof(addr))==0,"server IPv4 bind");
    }
    check(lwip_listen(fd,4)==0 && lwip_fcntl(fd,F_SETFL,O_NONBLOCK)==0,"nonblocking server listen");return fd;
}
template<class F> void eventually(F predicate,const char* label) {
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);
    while (!predicate()) {
        if (std::chrono::steady_clock::now()>=deadline) { check(false,label); }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    check(true,label);
}
struct Connection { int client=-1,peer=-1,listener=-1;uint64_t epoch=0,network=0; };
Connection establish(unsigned i,bool six,uint16_t port) {
    Connection c;c.network=100+i;c.listener=listening(i,six,port);uint8_t ip[16]={};
    check(lwip_inet_pton(six?AF_INET6:AF_INET,six?"fd80:1::3":"10.1.2.3",ip)==1,"numeric peer fixture");
    int result=hp_zt_bound_open(c.network,ip,six?16:4,port,&c.client,&c.epoch);
    if (result!=HP_ZT_BOUND_OK && result!=HP_ZT_BOUND_AGAIN) {
        std::cerr<<"native bound open result="<<result<<" errno="<<zts_errno<<" epoch_assigned="<<(c.epoch!=0)<<"\n";
    }
    check((result==HP_ZT_BOUND_OK || result==HP_ZT_BOUND_AGAIN) && c.client>=0 && c.epoch,"real network-bound connect");
    eventually([&]{
        if (c.peer<0) { c.peer=lwip_accept(c.listener,nullptr,nullptr); }
        return c.peer>=0 && hp_zt_bound_state(c.client,c.network,c.epoch)==HP_ZT_BOUND_OK;
    },"real TCP handshake deadline");
    check(lwip_fcntl(c.peer,F_SETFL,O_NONBLOCK)==0,"nonblocking accepted socket");return c;
}
void transfer(Connection& c) {
    const uint8_t data[]={0x31,0x32,0x33};uint32_t count=99;uint8_t received[8]={};
    check(hp_zt_bound_write(c.client,data,3,&count)==HP_ZT_BOUND_OK && count==3,"actual lwIP write accepted");
    int amount=-1;eventually([&]{amount=lwip_recv(c.peer,received,sizeof(received),MSG_DONTWAIT);return amount>=0;},"peer receive");
    check(amount==3 && std::memcmp(data,received,3)==0,"original network receives exact payload");
    check(hp_zt_bound_shutdown_write(c.client)==0,"actual half close");
    eventually([&]{amount=lwip_recv(c.peer,received,sizeof(received),MSG_DONTWAIT);return amount==0;},"peer sees write EOF");
    check(lwip_send(c.peer,data,3,MSG_DONTWAIT)==3,"peer responds after half close");
    eventually([&]{return hp_zt_bound_read(c.client,received,sizeof(received),&count)==HP_ZT_BOUND_OK;},"client read after half close");
    check(count==3 && std::memcmp(data,received,3)==0,"half close preserves actual read path");
    check(lwip_close(c.peer)==0,"peer close");c.peer=-1;
    eventually([&]{return hp_zt_bound_read(c.client,received,sizeof(received),&count)==0 && !count;},"client receives EOF");
    check(hp_zt_bound_state(c.client,c.network,c.epoch)==0,"original route proof survives peer EOF");
}
void dispose(Connection& c) {
    check(hp_zt_bound_close(c.client)==0,"actual client close");
    if (c.peer>=0) { check(lwip_close(c.peer)==0,"accepted close"); }
    check(lwip_close(c.listener)==0,"listener close");
}
void route_negatives() {
    ip_addr_t dest,source;ipaddr_aton("10.1.2.3",&dest);LOCK_TCPIP_CORE();
    check(hp_zt_route_locked(100,&dest,&source)==&clients[0],"overlapping IPv4 original network");
    check(hp_zt_route_locked(101,&dest,&source)==&clients[1],"overlapping IPv4 distinct network");
    check(hp_zt_route_locked(999,&dest,&source)==nullptr,"no default network fallback");
    clients[0].hp_ready=0;check(!hp_zt_route_locked(100,&dest,&source),"unready netif rejected");clients[0].hp_ready=1;
    netif_set_link_down(&clients[0]);check(!hp_zt_route_locked(100,&dest,&source),"link-down rejected");netif_set_link_up(&clients[0]);
    ipaddr_aton("10.8.0.1",&dest);check(!hp_zt_route_locked(100,&dest,&source),"IPv4 unrelated subnet rejected");
    auto& route=clients[0].hp_routes[0];route.bits=16;route.mask=lwip_htonl(0xffff0000u);
    route.network=lwip_htonl(0x0a080000u);route.via=lwip_htonl(0x0a010201u);clients[0].hp_route_count=1;
    check(hp_zt_route_locked(100,&dest,&source)==&clients[0],"original IPv4 on-link gateway proof");
    clients[0].hp_routes[1]=route;clients[0].hp_routes[1].bits=24;
    clients[0].hp_routes[1].mask=lwip_htonl(0xffffff00u);clients[0].hp_routes[1].via=lwip_htonl(0x0a090001u);
    clients[0].hp_route_count=2;
    check(!hp_zt_route_locked(100,&dest,&source),"invalid most-specific gateway cannot fall back to broad route");
    clients[0].hp_route_count=1;
    route.via=lwip_htonl(0x0a090001u);check(!hp_zt_route_locked(100,&dest,&source),"off-link gateway rejected");clients[0].hp_route_count=0;
    ipaddr_aton("fd80:1::3",&dest);
    check(hp_zt_route_locked(102,&dest,&source)==&clients[2] && hp_zt_route_locked(103,&dest,&source)==&clients[3],"real overlapping IPv6 prefix proof");
    netif_ip6_addr_set_state(&clients[2],0,IP6_ADDR_TENTATIVE);
    check(!hp_zt_route_locked(102,&dest,&source),"tentative IPv6 address rejected");netif_ip6_addr_set_state(&clients[2],0,IP6_ADDR_PREFERRED);
    // An extra valid/RA slot must never inherit the recorded source's prefix.
    ip6_addr_t extra;ip6addr_aton("fd90:2::1",&extra);
    netif_ip6_addr_set(&clients[2],1,&extra);netif_ip6_addr_set_state(&clients[2],1,IP6_ADDR_PREFERRED);
    clients[2].hp_prefix6=128;
    check(!hp_zt_route_locked(102,&dest,&source),"IPv6 source /128 cannot borrow another slot prefix");
    ipaddr_aton("fd90:2::2",&dest);clients[2].hp_prefix6=32;
    check(!hp_zt_route_locked(102,&dest,&source),"unrecorded global IPv6 source cannot replace original");
    std::memcpy(clients[2].hp_source6,extra.addr,16);clients[2].hp_prefix6=32;
    ipaddr_aton("fd80:1::3",&dest);
    check(!hp_zt_route_locked(102,&dest,&source),"new recorded source prefix cannot apply to old valid slot");
    std::memcpy(clients[2].hp_source6,netif_ip6_addr(&clients[2],0)->addr,16);
    clients[2].hp_prefix6=64;netif_ip6_addr_set_state(&clients[2],1,IP6_ADDR_INVALID);
    ipaddr_aton("fd80:2::3",&dest);check(!hp_zt_route_locked(102,&dest,&source),"IPv6 off-prefix rejected, never unconditional true");
    ipaddr_aton("fe80::3",&dest);check(!hp_zt_route_locked(102,&dest,&source),"unscoped link-local refused");
    UNLOCK_TCPIP_CORE();
}
void remove_isolation(Connection& survivor,unsigned removed) {
    LOCK_TCPIP_CORE();
    auto& n=clients[removed];const u8_t old_index=n.num;
    if (removed<2) {
        ip4_addr_t changed,old;ip4_addr_copy(old,*netif_ip4_addr(&n));ip4addr_aton("10.1.2.99",&changed);
        netif_set_ipaddr(&n,&changed);
        UNLOCK_TCPIP_CORE();
        check(hp_zt_bound_state(survivor.client,survivor.network,survivor.epoch)==0,"IPv4 change on overlapping network preserves other PCB");
        LOCK_TCPIP_CORE();netif_set_ipaddr(&n,&old);
    } else {
        ip6_addr_t old,changed;ip6_addr_copy(old,*netif_ip6_addr(&n,0));ip6addr_aton("fd80:1::99",&changed);
        netif_ip6_addr_set_state(&n,0,IP6_ADDR_INVALID);
        UNLOCK_TCPIP_CORE();
        check(hp_zt_bound_state(survivor.client,survivor.network,survivor.epoch)==0,"IPv6 invalidation preserves other bound PCB");
        LOCK_TCPIP_CORE();netif_ip6_addr_set_state(&n,0,IP6_ADDR_PREFERRED);netif_ip6_addr_set(&n,0,&changed);
        UNLOCK_TCPIP_CORE();
        check(hp_zt_bound_state(survivor.client,survivor.network,survivor.epoch)==0,"IPv6 address parts change preserves other bound PCB");
        LOCK_TCPIP_CORE();netif_ip6_addr_set(&n,0,&old);netif_ip6_addr_set_state(&n,0,IP6_ADDR_PREFERRED);
    }
    netif_remove(&n);
    UNLOCK_TCPIP_CORE();
    check(hp_zt_bound_state(survivor.client,survivor.network,survivor.epoch)==0,"removing overlapping network preserves other bound PCB");
    uint8_t bytes[8]={};uint32_t count=0;
    check(hp_zt_bound_write(survivor.client,reinterpret_cast<const uint8_t*>("s"),1,&count)==0 && count==1,"surviving network writes after other remove");
    eventually([&]{return lwip_recv(survivor.peer,bytes,sizeof(bytes),MSG_DONTWAIT)==1;},"surviving network actually receives after other remove");
    LOCK_TCPIP_CORE();n.next=netif_list;netif_list=&n;n.num=old_index;n.hp_generation+=1000;UNLOCK_TCPIP_CORE();
}
void old_generation(Connection& c,unsigned index) {
    uint8_t data[8]={};uint32_t amount=99;
    client_wire[index].drop=true;
    check(hp_zt_bound_write(c.client,reinterpret_cast<const uint8_t*>("x"),1,&amount)==0 && amount==1,"queue unacknowledged data");
    LOCK_TCPIP_CORE();
    struct tcp_pcb* pcb=tcp_active_pcbs;
    while (pcb && pcb->hp_generation!=c.epoch) { pcb=pcb->next; }
    check(pcb!=nullptr,"locate actual original PCB");
    auto& n=clients[index];const u8_t old_index=n.num;
    n.hp_generation+=1000;n.num=old_index; // Config changes retain the same index and live PCB.
    const auto before=client_wire[index].packets.load();
    check(tcp_rexmit(pcb)==ERR_OK,"force original unacknowledged segment retry");
    check(tcp_output(pcb)==ERR_RTE,"old generation rejects output on reused index");
    for (unsigned i=0;i<20;++i) { tcp_slowtmr(); }
    check(client_wire[index].packets.load()==before,"actual retransmission never emits on new generation");
    client_wire[index].drop=false;
    UNLOCK_TCPIP_CORE();
    check(hp_zt_bound_state(c.client,c.network,c.epoch)==HP_ZT_BOUND_ROUTE,"old stream status rejects replacement");
    check(lwip_send(c.peer,"z",1,MSG_DONTWAIT)==1,"old peer attempts data to reused interface");
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    check(lwip_recv(c.client,data,sizeof(data),MSG_DONTWAIT)<0,"actual input demux rejects old PCB generation");
}
}
int main() {
    std::cerr<<"phase: isolated tcpip init\n";
    tcpip_init(initialized,nullptr);
    { std::unique_lock<std::mutex> lock(ready_mutex);check(ready_changed.wait_for(lock,std::chrono::seconds(3),[]{return ready;}),"isolated lwIP init"); }
    for (unsigned i=0;i<4;++i) { setup(i,i>=2); }
    std::cerr<<"phase: real route negatives\n";route_negatives();
    std::cerr<<"phase: IPv4 handshakes\n";auto a=establish(0,false,2201),b=establish(1,false,2202);
    std::cerr<<"phase: IPv6 handshakes\n";auto v6a=establish(2,true,2203),v6b=establish(3,true,2204);
    std::cerr<<"phase: halfclose and EOF\n";transfer(a);transfer(v6a);dispose(a);dispose(v6a);
    std::cerr<<"phase: removal isolation\n";remove_isolation(b,0);remove_isolation(v6b,2);
    std::cerr<<"phase: generation retirement\n";old_generation(b,1);old_generation(v6b,3);dispose(b);dispose(v6b);
    std::cout<<"PASS: "<<checks<<" real lwIP in-memory IPv4/IPv6 checks; overlapping networks, half-close/EOF, route negatives, old-index output/retransmission/input rejection; no ZeroTier node or host socket\n";
}
