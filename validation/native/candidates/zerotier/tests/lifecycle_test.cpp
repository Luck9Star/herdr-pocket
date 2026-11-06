#include "HpLifecycle.hpp"
#include <cassert>
#include <atomic>
#include <future>
#include <thread>
#include <iostream>
using namespace ZeroTier;
using Clock=std::chrono::steady_clock;
int main() {
    HpWorkers workers;
    {HpLaunchGuard failed(workers,HpWorkers::Service);assert(static_cast<bool>(failed));}
    assert(workers.node_quiet());
    {HpLaunchGuard admitted(workers,HpWorkers::Service);assert(static_cast<bool>(admitted));admitted.commit();}
    assert(workers.active(HpWorkers::Service));
    {HpLaunchGuard duplicate(workers,HpWorkers::Service);assert(!duplicate);}
    assert(workers.active(HpWorkers::Service));workers.finish(HpWorkers::Service);
    assert(workers.begin(HpWorkers::Service));
    assert(!workers.begin(HpWorkers::Service));
    assert(workers.begin(HpWorkers::Callback));
    workers.finish(HpWorkers::Service);
    assert(!workers.node_quiet());
    assert(!workers.wait_node(Clock::now()+std::chrono::milliseconds(10)));
    assert(!workers.begin(HpWorkers::Callback)); // Timed out owner cannot be overwritten.
    workers.finish(HpWorkers::Callback);
    assert(workers.wait_node(Clock::now()+std::chrono::milliseconds(10)));
    assert(workers.begin(HpWorkers::Driver));
    assert(workers.node_quiet()); // Ordinary stop is distinct from permanent free.
    assert(!workers.wait_driver(Clock::now()+std::chrono::milliseconds(10)));
    workers.finish(HpWorkers::Driver);
    assert(workers.wait_driver(Clock::now()+std::chrono::milliseconds(10)));
    HpFrameGate gate;
    assert(gate.enter());gate.retire();assert(!gate.enter());
    std::promise<void> draining;std::atomic<bool> retired(false);
    auto drain=std::async(std::launch::async,[&]{draining.set_value();gate.drain();retired=true;});
    draining.get_future().wait();std::this_thread::sleep_for(std::chrono::milliseconds(10));assert(!retired);
    gate.leave();drain.get();assert(retired && !gate.enter());
    std::cout << "worker/frame helper offline: callback timeout preserves owner, duplicate admission refused, driver drain, late frame gate passed\n";
}
