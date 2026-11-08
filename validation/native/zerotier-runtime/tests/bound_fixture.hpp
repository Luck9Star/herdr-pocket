#pragma once
#include "hp_zt_bound.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <mutex>
namespace Boundary {
struct Gate {
    std::mutex mutex; std::condition_variable changed;
    bool armed=false,entered=false,released=false;
    void arm() { std::lock_guard<std::mutex> lock(mutex); armed=true; entered=false; released=false; }
    void block() {
        std::unique_lock<std::mutex> lock(mutex);
        if (!armed) { return; }
        armed=false; entered=true; changed.notify_all();
        changed.wait(lock,[&]{return released;});
    }
    void wait() {
        std::unique_lock<std::mutex> lock(mutex);
        if (!changed.wait_for(lock,std::chrono::seconds(3),[&]{return entered;})) { std::abort(); }
    }
    void open() { std::lock_guard<std::mutex> lock(mutex); released=true; changed.notify_all(); }
};
extern Gate opening,reading,writing,closing,checking;
extern std::atomic<int> open_result,read_result,write_result,close_result;
extern std::atomic<uint32_t> read_count,write_count;
extern std::atomic<int> opened,reads,writes,closed,shutdowns;
void change_epoch(uint64_t network);
}
