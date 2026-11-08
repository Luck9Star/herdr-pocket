// Fault-injected C/lwIP boundary. This is not a ZeroTier/lwIP network test.
#include "bound_fixture.hpp"
#include <map>
#include <cstring>
namespace Boundary {
Gate opening,reading,writing,closing,checking;
std::atomic<int> open_result{HP_ZT_BOUND_OK},read_result{HP_ZT_BOUND_AGAIN},write_result{HP_ZT_BOUND_OK},close_result{HP_ZT_BOUND_OK};
std::atomic<uint32_t> read_count{0},write_count{1};
std::atomic<int> opened{0},reads{0},writes{0},closed{0},shutdowns{0};
struct Socket { uint64_t network,epoch; };
std::mutex mutex;
std::map<int,Socket> sockets;
std::map<uint64_t,uint64_t> epochs;
int next_fd=1;
void change_epoch(uint64_t network) { std::lock_guard<std::mutex> lock(mutex); ++epochs[network]; }
}
extern "C" {
int hp_zt_bound_open(uint64_t network,const uint8_t*,uint32_t,uint16_t,int* fd,uint64_t* epoch) {
    ++Boundary::opened; Boundary::opening.block();
    std::lock_guard<std::mutex> lock(Boundary::mutex);
    *fd=Boundary::next_fd++; auto& generation=Boundary::epochs[network]; if (!generation) { generation=1; }
    *epoch=generation; Boundary::sockets.emplace(*fd,Boundary::Socket{network,generation});
    return Boundary::open_result.load();
}
int hp_zt_bound_state(int fd,uint64_t network,uint64_t epoch) {
    Boundary::checking.block(); std::lock_guard<std::mutex> lock(Boundary::mutex);
    auto it=Boundary::sockets.find(fd);
    return it!=Boundary::sockets.end() && it->second.network==network && it->second.epoch==epoch &&
        epoch==Boundary::epochs[network] ? HP_ZT_BOUND_OK : HP_ZT_BOUND_ROUTE;
}
int hp_zt_bound_read(int,uint8_t* data,uint32_t cap,uint32_t* count) {
    ++Boundary::reads; Boundary::reading.block(); *count=Boundary::read_count.load();
    if (*count<=cap) { std::memset(data,0x51,*count); }
    return Boundary::read_result.load();
}
int hp_zt_bound_write(int,const uint8_t*,uint32_t,uint32_t* count) {
    ++Boundary::writes; Boundary::writing.block(); *count=Boundary::write_count.load();
    return Boundary::write_result.load();
}
int hp_zt_bound_shutdown_write(int) { ++Boundary::shutdowns; return HP_ZT_BOUND_OK; }
int hp_zt_bound_close(int fd) {
    ++Boundary::closed; Boundary::closing.block();
    int result=Boundary::close_result.load();
    if (result==HP_ZT_BOUND_OK) { std::lock_guard<std::mutex> lock(Boundary::mutex); Boundary::sockets.erase(fd); }
    return result;
}
}
