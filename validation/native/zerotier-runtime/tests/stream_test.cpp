// Actual production manager + explicit synthetic C/lwIP boundary, no node.
#define main control_fixture_main
#include "manager_test.cpp"
#undef main
#include "bound_fixture.hpp"
#include <vector>
namespace {
uint8_t ip4[]={10,1,2,3};
uint8_t ip6[]={0xfd,0x80,0,0,0,0,0,0,0,0,0,0,0,0,0,3};
uint64_t join(uint64_t owner,uint64_t net) {
    uint64_t lease=0; check(hp_zt_network_join(owner,net,1000,&lease)==0 && lease,"network lease"); return lease;
}
uint64_t reserve(uint64_t owner,uint64_t lease,bool six=false) {
    uint64_t stream=0;
    check(hp_zt_stream_new(owner,lease,six?ip6:ip4,six?16:4,22,&stream)==0 && stream,"reserve numeric stream");
    return stream;
}
uint64_t connect(uint64_t owner,uint64_t lease,bool six=false) {
    auto stream=reserve(owner,lease,six);
    check(hp_zt_stream_open(owner,lease,stream,1000)==0,"open exact stream"); return stream;
}
void dispose(uint64_t owner,uint64_t lease,uint64_t stream) {
    check(hp_zt_stream_close(owner,lease,stream,1000)==0,"close exact stream");
    check(hp_zt_stream_release(owner,lease,stream)==0,"release exact closed stream");
}
void ordinary() {
    check(hp_zt_stream_abi_version()==1,"explicit stream ABI version");
    auto owner=create(); start(owner); auto a=join(owner,10),b=join(owner,20);
    uint64_t invalid=99;
    check(hp_zt_stream_new(owner,a,ip4,5,22,&invalid)==HP_ZT_MANAGED_ARGUMENT && !invalid,"reject unknown IP family");
    auto stream=reserve(owner,a); uint8_t data[8]={}; uint32_t length=99;
    check(hp_zt_stream_read(owner,a,stream,data,8,20,&length)==HP_ZT_MANAGED_BUSY && !length,"unopened cannot read");
    check(hp_zt_stream_open(owner,b,stream,20)==HP_ZT_MANAGED_STALE,"wrong lease cannot open");
    check(hp_zt_stream_open(owner,a,stream,1000)==0,"first open");
    const int opens=Boundary::opened.load();
    check(hp_zt_stream_open(owner,a,stream,1000)==HP_ZT_MANAGED_BUSY && Boundary::opened.load()==opens,"never replay connect");
    check(hp_zt_stream_read(owner,a,stream,data,8,20,&length)==HP_ZT_MANAGED_TIMEOUT && !length,"settled EAGAIN zero read timeout");
    Boundary::read_result=HP_ZT_BOUND_OK; Boundary::read_count=0;
    check(hp_zt_stream_read(owner,a,stream,data,8,20,&length)==0 && !length,"known zero EOF");
    check(hp_zt_stream_shutdown_write(owner,a,stream,20)==0,"half close");
    const int shutdowns=Boundary::shutdowns.load();
    check(hp_zt_stream_shutdown_write(owner,a,stream,20)==0 && Boundary::shutdowns.load()==shutdowns,"half close exact idempotence");
    Boundary::read_count=1;
    check(hp_zt_stream_read(owner,a,stream,data,8,20,&length)==0 && length==1,"half close retains reads");
    const int writes=Boundary::writes.load();
    check(hp_zt_stream_write(owner,a,stream,data,8,20,&length)==HP_ZT_MANAGED_CLOSING && !length && Boundary::writes.load()==writes,"half close forbids writes");
    check(hp_zt_stream_close(owner,b,stream,20)==HP_ZT_MANAGED_STALE,"wrong lease cannot close");
    dispose(owner,a,stream);
    check(hp_zt_stream_release(owner,a,stream)==HP_ZT_MANAGED_STALE,"released handle not arbitrary success");
    auto v6=connect(owner,b,true); dispose(owner,b,v6); finish(owner);
    Boundary::read_result=HP_ZT_BOUND_AGAIN; Boundary::read_count=0;
}
void blocked_io() {
    auto owner=create();start(owner);auto lease=join(owner,30);auto stream=connect(owner,lease);
    uint8_t data[8]={};uint32_t count=99;int result=-1;
    Boundary::reading.arm();
    std::thread reader([&]{result=hp_zt_stream_read(owner,lease,stream,data,8,1000,&count);}); Boundary::reading.wait();
    uint32_t other=99;
    check(hp_zt_stream_read(owner,lease,stream,data,8,20,&other)==HP_ZT_MANAGED_BUSY && !other,"per-read busy admission");
    check(hp_zt_stream_write(owner,lease,stream,data,8,20,&other)==HP_ZT_MANAGED_TIMEOUT,"opposite direction independently admitted waits original FFI");
    check(hp_zt_stream_cancel(owner,lease,stream)==0,"cancel blocked native read");
    check(hp_zt_stream_close(owner,lease,stream,20)==HP_ZT_MANAGED_TIMEOUT,"unfinished original read prevents fd close");
    check(hp_zt_stream_release(owner,lease,stream)==HP_ZT_MANAGED_BUSY,"unfinished read retains owner and quota");
    Boundary::reading.open();reader.join();
    check(result==HP_ZT_MANAGED_CANCELLED && !count,"late original read discarded");dispose(owner,lease,stream);
    stream=connect(owner,lease); Boundary::writing.arm();count=99;result=-1;
    std::thread writer([&]{result=hp_zt_stream_write(owner,lease,stream,data,8,1000,&count);});Boundary::writing.wait();
    const int writes=Boundary::writes.load();
    check(hp_zt_stream_write(owner,lease,stream,data,8,20,&other)==HP_ZT_MANAGED_BUSY,"per-write busy");
    check(hp_zt_stream_cancel(owner,lease,stream)==0,"cancel dispatched write");
    check(hp_zt_stream_close(owner,lease,stream,20)==HP_ZT_MANAGED_TIMEOUT,"write original retains fd");
    Boundary::writing.open();writer.join();
    check(result==HP_ZT_MANAGED_UNKNOWN_WRITE && !count && Boundary::writes.load()==writes,"unknown write is not replayed");
    dispose(owner,lease,stream);finish(owner);
}
void pending_open_capacity() {
    auto owner=create();start(owner);auto lease=join(owner,40);auto stream=reserve(owner,lease);
    Boundary::opening.arm();int result=-1;
    std::thread opener([&]{result=hp_zt_stream_open(owner,lease,stream,1000);});Boundary::opening.wait();
    std::vector<uint64_t> extra;
    for (unsigned i=1;i<HP_ZT_MAX_STREAMS;++i) { extra.push_back(reserve(owner,lease)); }
    uint64_t overflow=99;
    check(hp_zt_stream_new(owner,lease,ip4,4,22,&overflow)==HP_ZT_MANAGED_CAPACITY && !overflow,"pending open occupies global32");
    hp_zt_stream_cancel(owner,lease,stream);
    check(hp_zt_stream_close(owner,lease,stream,20)==HP_ZT_MANAGED_TIMEOUT,"late socket allocation retained");
    check(hp_zt_stream_release(owner,lease,stream)==HP_ZT_MANAGED_BUSY,"pending open not retired");
    Boundary::opening.open();opener.join();
    check(result==HP_ZT_MANAGED_CANCELLED,"late open never published ready");
    Boundary::close_result=HP_ZT_BOUND_ERROR;
    check(hp_zt_stream_close(owner,lease,stream,20)==HP_ZT_MANAGED_NATIVE,"real close error visible");
    check(hp_zt_stream_release(owner,lease,stream)==HP_ZT_MANAGED_BUSY,"close error retains quota");
    check(hp_zt_stream_new(owner,lease,ip4,4,22,&overflow)==HP_ZT_MANAGED_CAPACITY,"close failure still occupies slot");
    Boundary::close_result=HP_ZT_BOUND_OK;dispose(owner,lease,stream);
    auto next=reserve(owner,lease);check(next!=stream,"stream handles never reused");dispose(owner,lease,next);
    for (auto h:extra) { dispose(owner,lease,h); } finish(owner);
}
void leave_and_generation() {
    auto owner=create();start(owner);auto a=join(owner,50),b=join(owner,60);
    auto x=connect(owner,a),y=connect(owner,b);uint8_t data[8]={};uint32_t count=99;int result=-1;
    Boundary::reading.arm();
    std::thread reader([&]{result=hp_zt_stream_read(owner,a,x,data,8,1000,&count);});Boundary::reading.wait();
    const int closes=Boundary::closed.load(),native_leaves=leaves.load();
    check(hp_zt_network_leave(owner,a,20)==HP_ZT_MANAGED_TIMEOUT && leaves.load()==native_leaves,"leave waits original own read");
    uint32_t written=0;
    check(hp_zt_stream_write(owner,b,y,data,8,20,&written)==0 && written==1,"other network remains usable");
    Boundary::reading.open();reader.join();check(result==HP_ZT_MANAGED_CANCELLED,"leave wakes admitted reader");
    check(hp_zt_network_leave(owner,a,1000)==0 && Boundary::closed.load()==closes+1,"only own lease stream closed");
    check(hp_zt_stream_close(owner,a,x,20)==0,"closed record survives network leave");
    check(hp_zt_stream_release(owner,a,x)==0,"exact release after network leave");
    Boundary::change_epoch(60);
    const int writes=Boundary::writes.load();
    check(hp_zt_stream_write(owner,b,y,data,8,20,&written)==HP_ZT_MANAGED_ROUTE && !written && Boundary::writes.load()==writes,"old generation cannot dispatch on new netif");
    dispose(owner,b,y);finish(owner);
}
void late_postcheck_and_stop() {
    auto owner=create();start(owner);auto lease=join(owner,70);auto stream=connect(owner,lease);
    Boundary::read_result=HP_ZT_BOUND_OK;Boundary::read_count=1;
    uint8_t data[8]={};uint32_t count=99;int result=-1;
    Boundary::reading.arm();
    std::thread reader([&]{result=hp_zt_stream_read(owner,lease,stream,data,8,100,&count);});Boundary::reading.wait();
    Boundary::checking.arm();Boundary::reading.open();Boundary::checking.wait();
    std::this_thread::sleep_for(std::chrono::milliseconds(120));Boundary::checking.open();reader.join();
    check(result==HP_ZT_MANAGED_CANCELLED && !count,"late route postcheck cannot publish bytes");dispose(owner,lease,stream);
    Boundary::read_result=HP_ZT_BOUND_AGAIN;Boundary::read_count=0;
    stream=connect(owner,lease);Boundary::closing.arm();result=-1;
    std::thread closer([&]{result=hp_zt_stream_close(owner,lease,stream,1000);});Boundary::closing.wait();
    const int before_stop=stops.load();
    check(hp_zt_device_stop(owner,20)==HP_ZT_MANAGED_TIMEOUT && stops.load()==before_stop,"device cannot stop stack before original close");
    check(hp_zt_device_release(owner,20)==HP_ZT_MANAGED_BUSY,"original close retains device owner");
    Boundary::closing.open();closer.join();check(result==0,"original close actually returned");
    check(hp_zt_device_stop(owner,1000)==0,"device stop after drain");
    check(hp_zt_device_release(owner,1000)==HP_ZT_MANAGED_BUSY,"closed records require explicit release");
    check(hp_zt_stream_close(owner,lease,stream,20)==0 && hp_zt_stream_release(owner,lease,stream)==0,"exact cleanup after device stop");
    check(hp_zt_device_release(owner,1000)==0,"device release after original streams retired");
}
void offline_join_and_inconsistent_boundary() {
    auto owner=create();start(owner);node_online=false;
    auto lease=join(owner,80);uint32_t phase=0,online_status=1;
    check(hp_zt_network_status(owner,lease,1000,&phase,&online_status)==0 && phase==HP_ZT_NETWORK_REQUESTING && !online_status,
          "constructed offline node permits one join and stays requesting");
    uint64_t pending=99;const int joins_before=joins.load();node_id=0;
    check(hp_zt_network_join(owner,81,20,&pending)==HP_ZT_MANAGED_TIMEOUT && !pending && joins.load()==joins_before,
          "node construction timeout never calls join");
    int joined=-1;
    std::thread waiter([&]{joined=hp_zt_network_join(owner,81,1000,&pending);});
    std::this_thread::sleep_for(std::chrono::milliseconds(10));node_id=public_id;waiter.join();
    check(joined==0 && pending && joins.load()==joins_before+1,"original join waits constructed expected identity exactly once");
    node_online=true;auto stream=connect(owner,lease);uint8_t bytes[8]={};uint32_t count=99;
    Boundary::write_result=HP_ZT_BOUND_AGAIN;Boundary::write_count=1;const int writes=Boundary::writes.load();
    check(hp_zt_stream_write(owner,lease,stream,bytes,8,20,&count)==HP_ZT_MANAGED_UNKNOWN_WRITE && !count && Boundary::writes.load()==writes+1,
          "inconsistent AGAIN with consumed write is never replayed");dispose(owner,lease,stream);
    Boundary::write_result=HP_ZT_BOUND_OK;Boundary::write_count=1;stream=connect(owner,lease);
    Boundary::read_result=HP_ZT_BOUND_AGAIN;Boundary::read_count=1;
    check(hp_zt_stream_read(owner,lease,stream,bytes,8,20,&count)==HP_ZT_MANAGED_CANCELLED && !count,
          "consumed read cannot become retryable timeout");dispose(owner,lease,stream);
    Boundary::read_count=0;finish(owner);
}
}
int main() {
    ordinary();blocked_io();pending_open_capacity();leave_and_generation();late_postcheck_and_stop();offline_join_and_inconsistent_boundary();
    std::cout<<"PASS: "<<checks<<" production-manager stream checks; fault-injected C boundary, no overlay node\n";
}
