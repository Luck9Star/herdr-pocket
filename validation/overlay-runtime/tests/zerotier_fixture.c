/* Independent, in-memory ABI fixture. No libzt, socket, identity, DNS or disk. */
#include "../../native/zerotier-runtime/hp_zt_manager.h"
#include <pthread.h>
#include <string.h>
#include <assert.h>

typedef struct { uint64_t id, owner, network; } Network;
typedef struct {
    uint64_t id, owner, lease;
    int opened, cancelled, closed, half;
    uint32_t len;
    uint8_t bytes[65536];
} Stream;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
static Network networks[32];
static Stream streams[32];
static uint64_t next_network = 1, next_stream = 1;
static int metrics[10], close_fail, leave_fail, open_gate = 1, join_gate = 1, unknown_write;
static uint32_t network_phase = 2, device_online = 1;
static Network *network(uint64_t owner, uint64_t id) {
    for (int i=0;i<32;i++) if (id && networks[i].id==id && networks[i].owner==owner) return &networks[i];
    return NULL;
}
static Stream *stream(uint64_t owner, uint64_t lease, uint64_t id) {
    for (int i=0;i<32;i++) if (id && streams[i].id==id && streams[i].owner==owner && streams[i].lease==lease) return &streams[i];
    return NULL;
}
void hp_zt_fixture_reset(void) {
    pthread_mutex_lock(&mu);
    assert(metrics[0]==0 && metrics[1]==0);
    memset(metrics,0,sizeof(metrics));
    close_fail=leave_fail=unknown_write=0; open_gate=join_gate=1; network_phase=2; device_online=1;
    pthread_mutex_unlock(&mu);
}
void hp_zt_fixture_control(int op) {
    pthread_mutex_lock(&mu);
    if(op==1) close_fail=1;
    if(op==2) close_fail=0;
    if(op==3) open_gate=0;
    if(op==4) open_gate=1;
    if(op==5) unknown_write=1;
    if(op==6) unknown_write=0;
    if(op==7) join_gate=0;
    if(op==8) join_gate=1;
    if(op==9) leave_fail=1;
    if(op==10) leave_fail=0;
    pthread_cond_broadcast(&cv); pthread_mutex_unlock(&mu);
}
void hp_zt_fixture_state(uint32_t phase, uint32_t online) {
    pthread_mutex_lock(&mu); network_phase=phase; device_online=online; pthread_mutex_unlock(&mu);
}
int hp_zt_fixture_metric(int i) {
    pthread_mutex_lock(&mu); int result=(i>=0 && i<10)?metrics[i]:-1; pthread_mutex_unlock(&mu); return result;
}
uint32_t hp_zt_manager_abi_version(void) { return 1; }
uint32_t hp_zt_stream_abi_version(void) { return 1; }
int hp_zt_network_join(uint64_t owner,uint64_t id,uint32_t timeout,uint64_t *out) {
    if(!owner || !id || !timeout || !out) return HP_ZT_MANAGED_ARGUMENT;
    *out=0; pthread_mutex_lock(&mu); metrics[8]++;
    while(!join_gate) pthread_cond_wait(&cv,&mu);
    Network *slot=NULL; for(int i=0;i<32;i++) if(!networks[i].id){slot=&networks[i];break;}
    if(!slot){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_CAPACITY;}
    *slot=(Network){.id=next_network++,.owner=owner,.network=id}; *out=slot->id;
    metrics[0]++;metrics[2]++;pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_network_status(uint64_t owner,uint64_t lease,uint32_t timeout,uint32_t *phase,uint32_t *online) {
    if(!timeout || !phase || !online)return HP_ZT_MANAGED_ARGUMENT;
    pthread_mutex_lock(&mu); if(!network(owner,lease)){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    *phase=network_phase;*online=device_online;pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_network_leave(uint64_t owner,uint64_t lease,uint32_t timeout) {
    if(!timeout)return HP_ZT_MANAGED_ARGUMENT;
    pthread_mutex_lock(&mu);Network *n=network(owner,lease);
    if(!n){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    if(leave_fail){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_TIMEOUT;}
    for(int i=0;i<32;i++) if(streams[i].id && streams[i].owner==owner && streams[i].lease==lease) {
        pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_BUSY;
    }
    memset(n,0,sizeof(*n));metrics[0]--;metrics[3]++;pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_stream_new(uint64_t owner,uint64_t lease,const uint8_t *ip,uint32_t len,uint16_t port,uint64_t *out) {
    if(!out || !port || !ip || (len!=4 && len!=16))return HP_ZT_MANAGED_ARGUMENT;
    *out=0;pthread_mutex_lock(&mu);
    Network *n=network(owner,lease);
    if(!n){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    /* Isolated synthetic network destination rule, not real route evidence. */
    if(ip[len-1]!=(uint8_t)n->network){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_ROUTE;}
    Stream *s=NULL;for(int i=0;i<32;i++) if(!streams[i].id){s=&streams[i];break;}
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_CAPACITY;}
    *s=(Stream){.id=next_stream++,.owner=owner,.lease=lease};*out=s->id;
    metrics[1]++;if(len==16)metrics[7]++;pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_stream_open(uint64_t owner,uint64_t lease,uint64_t id,uint32_t timeout) {
    if(!timeout)return HP_ZT_MANAGED_ARGUMENT;
    pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    metrics[4]++;while(!open_gate && !s->cancelled)pthread_cond_wait(&cv,&mu);
    int code=s->cancelled?HP_ZT_MANAGED_CANCELLED:network_phase!=2 || !device_online?HP_ZT_MANAGED_ROUTE:0;
    if(!code)s->opened=1;pthread_mutex_unlock(&mu);return code;
}
int hp_zt_stream_read(uint64_t owner,uint64_t lease,uint64_t id,uint8_t *data,uint32_t cap,uint32_t timeout,uint32_t *len) {
    if(!timeout || !data || !cap || cap>65536 || !len)return HP_ZT_MANAGED_ARGUMENT;
    *len=0;pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    if(s->cancelled || !s->opened){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_CANCELLED;}
    uint32_t count=s->len<cap?s->len:cap;memcpy(data,s->bytes,count);memmove(s->bytes,s->bytes+count,s->len-count);s->len-=count;*len=count;
    int code=count || s->half?0:HP_ZT_MANAGED_TIMEOUT;pthread_mutex_unlock(&mu);return code;
}
int hp_zt_stream_write(uint64_t owner,uint64_t lease,uint64_t id,const uint8_t *data,uint32_t len,uint32_t timeout,uint32_t *written) {
    if(!timeout || !data || !len || len>65536 || !written)return HP_ZT_MANAGED_ARGUMENT;
    *written=0;pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    metrics[5]++;
    if(unknown_write || s->cancelled || !s->opened || s->half || s->len+len>65536){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_UNKNOWN_WRITE;}
    memcpy(s->bytes+s->len,data,len);s->len+=len;*written=len;pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_stream_shutdown_write(uint64_t owner,uint64_t lease,uint64_t id,uint32_t timeout) {
    if(!timeout)return HP_ZT_MANAGED_ARGUMENT;
    pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s || s->cancelled){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    s->half=1;pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_stream_cancel(uint64_t owner,uint64_t lease,uint64_t id) {
    pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    s->cancelled=1;pthread_cond_broadcast(&cv);pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_stream_close(uint64_t owner,uint64_t lease,uint64_t id,uint32_t timeout) {
    if(!timeout)return HP_ZT_MANAGED_ARGUMENT;
    pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    if(close_fail){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_TIMEOUT;}
    s->closed=1;s->cancelled=1;pthread_cond_broadcast(&cv);pthread_mutex_unlock(&mu);return 0;
}
int hp_zt_stream_release(uint64_t owner,uint64_t lease,uint64_t id) {
    pthread_mutex_lock(&mu);Stream *s=stream(owner,lease,id);
    if(!s){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_STALE;}
    if(!s->closed){pthread_mutex_unlock(&mu);return HP_ZT_MANAGED_BUSY;}
    memset(s,0,sizeof(*s));metrics[1]--;pthread_mutex_unlock(&mu);return 0;
}
