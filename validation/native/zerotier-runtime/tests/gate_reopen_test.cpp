// Actual HpFrameGate reopen semantics: a per-network DOWN drain re-admits
// other networks' frames, while the process-shutdown seal keeps the gate
// closed for good no matter what races it. Header-only production class,
// no lwIP/NodeService/Node or identity involved.
#include "HpLifecycle.hpp"
#include <atomic>
#include <chrono>
#include <future>
#include <iostream>
#include <mutex>
#include <thread>
namespace {
unsigned checks=0;
void check(bool b,const char* text) { if (!b) { std::cerr<<"FAIL: "<<text<<'\n'; std::exit(1); } ++checks; }
}
using ZeroTier::HpFrameGate;
using ZeroTier::HpFrameLease;
int main() {
    { // Fresh gate admits, releases and reports quiet.
        HpFrameGate gate;
        check(gate.enter(),"fresh gate admits");
        check(!gate.quiet(),"held lease is not quiet");
        gate.leave();
        check(gate.quiet(),"released lease is quiet");
    }
    { // Per-network DOWN semantics: drain waits for the lease, closes, and
      // reopen() re-admits so other networks keep receiving frames.
        HpFrameGate gate;
        check(gate.enter(),"pre-drain lease admitted");
        std::atomic<bool> drained(false);
        auto wait=std::async(std::launch::async,[&]{ gate.drain(); drained=true; });
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        check(!drained.load(),"drain waits for the lease holder");
        gate.leave(); wait.get();
        check(drained.load() && !gate.enter(),"drain closes the gate");
        gate.reopen();
        check(gate.enter(),"unsealed drain reopens for other networks");
        gate.leave();
        for (int i=0;i<3;++i) { gate.drain(); gate.reopen(); check(gate.enter(),"repeated DOWN drain+reopen cycles admit"); gate.leave(); }
    }
    { // Concurrent leases: both admitted, one drain retires both. Release
      // before joining the drain: the async future's destructor blocks, so
      // RAII leases outliving it would self-deadlock the harness.
        HpFrameGate gate;
        check(gate.enter() && gate.enter(),"two concurrent leases admitted");
        std::atomic<bool> drained(false);
        auto wait=std::async(std::launch::async,[&]{ gate.drain(); drained=true; });
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        check(!drained.load(),"drain waits for both lease holders");
        gate.leave(); gate.leave();
        wait.get();
        check(drained.load() && !gate.enter(),"drain retires both leases and closes");
    }
    { // RAII lease: dropping it releases; a lease on a closed gate is falsy
      // and its destruction must not underflow the counter.
        HpFrameGate gate;
        { HpFrameLease lease(gate); check(static_cast<bool>(lease),"RAII lease enters"); }
        check(gate.quiet(),"RAII lease releases on scope exit");
        gate.retire();
        { HpFrameLease refused(gate); check(!refused,"lease on retired gate refused"); }
        check(gate.quiet(),"refused lease leaves no counter residue");
    }
    { // Process shutdown semantics: once sealed, drain closes forever and
      // NO reopen -- even a racing unconditional one -- re-admits.
        HpFrameGate gate;
        gate.seal();
        check(!gate.enter(),"sealed gate refuses before drain");
        gate.drain();
        gate.reopen();                       // e.g. a DOWN path whose flag check lost the race
        check(!gate.enter(),"reopen after shutdown drain stays closed");
        gate.seal(); gate.reopen();          // sealing is one-way, reopen stays a no-op
        check(!gate.enter(),"double seal keeps the gate closed");
    }
    { // The B1 interleaving: seal while a lease is outstanding, drain waits
      // for it, and the late reopen still cannot re-admit.
        HpFrameGate gate;
        check(gate.enter(),"lease admitted before shutdown");
        gate.seal();
        std::atomic<bool> drained(false);
        auto wait=std::async(std::launch::async,[&]{ gate.drain(); drained=true; });
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        check(!drained.load(),"shutdown drain still waits for the lease holder");
        gate.leave(); wait.get();
        check(drained.load(),"shutdown drain returns after lease release");
        gate.reopen();
        check(!gate.enter(),"late reopen after sealed drain admits nothing");
        { HpFrameLease refused(gate); check(!refused,"frame callback lease refused for good"); }
    }
    std::cout<<"PASS: "<<checks<<" HpFrameGate reopen checks; per-network DOWN drain+reopen re-admits, sealed shutdown drain never reopens\n";
}
