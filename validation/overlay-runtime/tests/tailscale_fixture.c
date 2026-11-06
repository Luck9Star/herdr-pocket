/* Independent hp_ts ABI fixture. No socket, DNS, tsnet, credentials or files. */
#include "../../native/tailscale-runtime/hp_ts.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint64_t id,ctx; hp_ts_store_callbacks cb; int state,login,stop_fail,late,inflight,closed; } Node;
typedef struct { uint64_t id,node; int closed,half; uint32_t len; uint8_t bytes[65536]; } Stream;
static pthread_mutex_t mu=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv=PTHREAD_COND_INITIALIZER;
static Node nodes[8]; static Stream streams[32];
static uint64_t next_node=1,next_stream=1;
static int start_gate=1,login_gate=1,metrics[12];
static Node *find_node(uint64_t id) { for(int i=0;i<8;i++) if(nodes[i].id==id && id) return &nodes[i]; return NULL; }
static Stream *find_stream(uint64_t id) { for(int i=0;i<32;i++) if(streams[i].id==id && id) return &streams[i]; return NULL; }
void hp_ts_fixture_reset(void) { pthread_mutex_lock(&mu); memset(metrics,0,sizeof(metrics));start_gate=1;login_gate=1;pthread_mutex_unlock(&mu); }
void hp_ts_fixture_control(int op) {
 pthread_mutex_lock(&mu);
 if(op==1) { start_gate=0; }
 if(op==2) { start_gate=1; }
 if(op==3) { for(int i=0;i<8;i++) { nodes[i].stop_fail=0; } }
 if(op==4) { login_gate=0; }
 if(op==5) { login_gate=1; }
 pthread_cond_broadcast(&cv);
 pthread_mutex_unlock(&mu);
}
int hp_ts_fixture_metric(int index) { pthread_mutex_lock(&mu);int out=(index>=0 && index<12)?metrics[index]:-1;pthread_mutex_unlock(&mu);return out; }
uint32_t hp_ts_abi_version(void) {return 1;}
int32_t hp_ts_node_new(uint8_t *config,uint32_t len,hp_ts_store_callbacks *store,uint64_t ctx,uint64_t *out) {
 if(!config || !len || len>8192 || !store || !store->read || !store->write || !store->release || !out)return HP_TS_INVALID;
 char text[8193];memcpy(text,config,len);text[len]=0;*out=0;
 pthread_mutex_lock(&mu);Node *slot=NULL;for(int i=0;i<8;i++)if(!nodes[i].id){slot=&nodes[i];break;}
 if(!slot){pthread_mutex_unlock(&mu);return HP_TS_LIMIT;}
 *slot=(Node){.id=next_node++,.ctx=ctx,.cb=*store,.state=0,.stop_fail=strstr(text,"stop-fail")!=NULL,.late=strstr(text,"late-start")!=NULL};
 *out=slot->id;metrics[0]++;metrics[2]++;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
static int store_probe(Node *n) {
 const uint8_t key[]={ 'k',0,255 },value[]={ 'v',0,'x' };uint8_t *data=NULL;uint32_t len=0,found=0;
 if(n->cb.read(n->ctx,key,3,&data,&len,&found)!=0 || found!=0 || data || len)return HP_TS_IO;
 if(n->cb.write(n->ctx,key,3,value,3,0)!=0)return HP_TS_IO;
 if(n->cb.read(n->ctx,key,3,&data,&len,&found)!=0 || found!=1 || !data || len!=3)return HP_TS_IO;
 int same=memcmp(data,value,3)==0;n->cb.release(n->ctx,data,len);if(!same)return HP_TS_IO;
 if(n->cb.write(n->ctx,NULL,0,NULL,0,0)!=0)return HP_TS_IO;
 data=NULL;len=0;found=0;
 if(n->cb.read(n->ctx,NULL,0,&data,&len,&found)!=0 || found!=1 || len!=0 || data)return HP_TS_IO;
 if(n->cb.write(n->ctx,NULL,0,NULL,0,1)!=0)return HP_TS_IO;
 data=NULL;len=0;found=9;
 if(n->cb.read(n->ctx,NULL,0,&data,&len,&found)!=0 || found!=0)return HP_TS_IO;
 if(n->cb.write(n->ctx,key,3,NULL,0,1)!=0)return HP_TS_IO;
 return HP_TS_OK;
}
int32_t hp_ts_node_start(uint64_t id,uint32_t timeout) {
 if(!timeout || timeout>60000)return HP_TS_INVALID;
 pthread_mutex_lock(&mu);Node *n=find_node(id);if(!n){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}
 n->inflight++;metrics[3]++;Node copy=*n;pthread_mutex_unlock(&mu);
 int result=store_probe(&copy);
 pthread_mutex_lock(&mu);while(n->late && !start_gate)pthread_cond_wait(&cv,&mu);
 n->inflight--;if(result==0)n->state=1;pthread_cond_broadcast(&cv);pthread_mutex_unlock(&mu);return result;
}
int32_t hp_ts_node_status(uint64_t id,uint32_t timeout,uint8_t *data,uint32_t cap,uint32_t *len) {
 if(!timeout || timeout>60000 || !len)return HP_TS_INVALID;
 pthread_mutex_lock(&mu);Node *n=find_node(id);if(!n){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}
 const char *states[]={"Starting","NeedsLogin","NeedsMachineAuth","Running","Closing","Stopped"};
 char text[256];int size=snprintf(text,sizeof(text),"{\"state\":\"%s\",\"auth_url\":\"%s\"}",states[n->state],n->login?"https://login.fixture.invalid/a/token?x=1":"");
 *len=(uint32_t)size;if(cap<(uint32_t)size || !data){pthread_mutex_unlock(&mu);return HP_TS_BUFFER;}
 memcpy(data,text,(size_t)size);pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_node_begin_login(uint64_t id,uint32_t timeout) {
 if(!timeout || timeout>60000)return HP_TS_INVALID;
 pthread_mutex_lock(&mu);Node *n=find_node(id);if(!n){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}
 metrics[9]++;while(!login_gate)pthread_cond_wait(&cv,&mu);
 n->login=1;n->state=2;metrics[5]++;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_node_dial(uint64_t id,uint8_t *address,uint32_t len,uint32_t timeout,uint64_t *out) {
 if(!timeout || timeout>60000 || !address || !len || !out) { return HP_TS_INVALID; }
 *out=0;
 pthread_mutex_lock(&mu);Node *n=find_node(id);if(!n){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}
 if(n->state!=3){pthread_mutex_unlock(&mu);return HP_TS_NOT_RUNNING;}
 Stream *slot=NULL;for(int i=0;i<32;i++)if(!streams[i].id){slot=&streams[i];break;}
 if(!slot){pthread_mutex_unlock(&mu);return HP_TS_LIMIT;}
 *slot=(Stream){.id=next_stream++,.node=id};*out=slot->id;metrics[6]++;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_stream_read(uint64_t id,uint8_t *data,uint32_t cap,uint32_t timeout,uint32_t *len) {
 if(!timeout || timeout>60000 || !data || !cap || cap>65536 || !len) { return HP_TS_INVALID; }
 *len=0;
 pthread_mutex_lock(&mu);Stream *s=find_stream(id);if(!s){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}
 if(s->closed){pthread_mutex_unlock(&mu);return HP_TS_CANCELLED;}
 if(!s->len){int code=s->half?HP_TS_OK:HP_TS_TIMEOUT;pthread_mutex_unlock(&mu);return code;}
 uint32_t count=s->len<cap?s->len:cap;memcpy(data,s->bytes,count);memmove(s->bytes,s->bytes+count,s->len-count);s->len-=count;*len=count;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_stream_write(uint64_t id,uint8_t *data,uint32_t len,uint32_t timeout,uint32_t *written) {
 if(!timeout || timeout>60000 || !data || !len || len>65536 || !written) { return HP_TS_INVALID; }
 *written=0;
 pthread_mutex_lock(&mu);Stream *s=find_stream(id);if(!s){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}
 if(s->closed || s->half || s->len+len>65536){pthread_mutex_unlock(&mu);return HP_TS_UNKNOWN_WRITE;}
 memcpy(s->bytes+s->len,data,len);s->len+=len;*written=len;metrics[7]++;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_stream_shutdown_write(uint64_t id,uint32_t timeout) {
 if(!timeout || timeout>60000) { return HP_TS_INVALID; }
 pthread_mutex_lock(&mu);Stream *s=find_stream(id);
 if(!s){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}s->half=1;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_stream_cancel(uint64_t id) {pthread_mutex_lock(&mu);Stream *s=find_stream(id);if(s)s->closed=1;pthread_mutex_unlock(&mu);return s?HP_TS_OK:HP_TS_NOT_FOUND;}
int32_t hp_ts_stream_close(uint64_t id,uint32_t timeout) {if(!timeout || timeout>60000)return HP_TS_INVALID;return hp_ts_stream_cancel(id);}
int32_t hp_ts_stream_release(uint64_t id) {pthread_mutex_lock(&mu);Stream *s=find_stream(id);
 if(!s){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}if(!s->closed){pthread_mutex_unlock(&mu);return HP_TS_BUSY;}
 memset(s,0,sizeof(*s));metrics[8]++;pthread_mutex_unlock(&mu);return HP_TS_OK;}
int32_t hp_ts_node_cancel(uint64_t id) {return hp_ts_node_close(id,1);}
int32_t hp_ts_node_close(uint64_t id,uint32_t timeout) {
 if(!timeout || timeout>60000) { return HP_TS_INVALID; }
 pthread_mutex_lock(&mu);Node *n=find_node(id);
 if(!n){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}metrics[4]++;n->state=4;
 if(n->inflight || n->stop_fail){pthread_mutex_unlock(&mu);return HP_TS_TIMEOUT;}
 for(int i=0;i<32;i++)if(streams[i].id && streams[i].node==id){pthread_mutex_unlock(&mu);return HP_TS_BUSY;}
 n->closed=1;n->state=5;pthread_mutex_unlock(&mu);return HP_TS_OK;
}
int32_t hp_ts_node_release(uint64_t id) {pthread_mutex_lock(&mu);Node *n=find_node(id);
 if(!n){pthread_mutex_unlock(&mu);return HP_TS_NOT_FOUND;}if(!n->closed || n->inflight){pthread_mutex_unlock(&mu);return HP_TS_BUSY;}
 memset(n,0,sizeof(*n));metrics[1]++;metrics[2]--;pthread_mutex_unlock(&mu);return HP_TS_OK;}
void hp_ts_fixture_running(uint64_t context) {pthread_mutex_lock(&mu);for(int i=0;i<8;i++)if(nodes[i].id && nodes[i].ctx==context)nodes[i].state=3;pthread_mutex_unlock(&mu);}
void hp_ts_fixture_all_running(void) {pthread_mutex_lock(&mu);for(int i=0;i<8;i++)if(nodes[i].id)nodes[i].state=3;pthread_mutex_unlock(&mu);}
