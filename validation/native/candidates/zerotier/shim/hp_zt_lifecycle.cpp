/* herdr-pocket: low-level process-global safety adapter. The managed owner
 * epoch and stream/API admission gates remain the caller's responsibility. */
#include "hp_zt.h"
#include "ZeroTierSockets.h"
namespace {
int result(int native) {
    if (native==ZTS_ERR_OK) { return HP_ZT_OK; }
    if (native==ZTS_ERR_ARG) { return HP_ZT_INVALID_ARGUMENT; }
    if (native==ZTS_ERR_TIMEOUT) { return HP_ZT_TIMEOUT; }
    if (native==ZTS_ERR_BUSY) { return HP_ZT_BUSY; }
    return HP_ZT_UNAVAILABLE;
}
}
extern "C" int hp_zt_node_stop(uint32_t timeout_ms) {
    try { return result(zts_node_stop_with_timeout(timeout_ms)); }
    catch (...) { return HP_ZT_UNAVAILABLE; }
}
extern "C" int hp_zt_node_free(uint32_t timeout_ms) {
    try { return result(zts_node_free_with_timeout(timeout_ms)); }
    catch (...) { return HP_ZT_UNAVAILABLE; }
}
extern "C" int hp_zt_node_quiescent(void) {
    try { return zts_node_is_quiescent()==1 ? 1 : 0; }
    catch (...) { return 0; }
}
