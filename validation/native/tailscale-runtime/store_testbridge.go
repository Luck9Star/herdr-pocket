//go:build hp_ts_test

package main

/*
#include "hp_ts.h"
#include <stdlib.h>
#include <string.h>
static int bridge_mode, bridge_releases, bridge_writes, bridge_deleted;
static uint32_t bridge_written_len;
static uint8_t bridge_value[16];
static int32_t bridge_read(uint64_t ctx,const uint8_t *key,uint32_t key_len,uint8_t **data,uint32_t *len,uint32_t *found) {
 *data=NULL;*len=0;*found=0;
 if (bridge_mode==0) return 0;
 *found=1;
 if (bridge_mode==1) return 0;
 *data=malloc(3);memcpy(*data,"abc",3);*len=3;
 if (bridge_mode==3) return 8;
 if (bridge_mode==4) *len=262145;
 if (bridge_mode==5) *found=2;
 return 0;
}
static int32_t bridge_write(uint64_t ctx,const uint8_t *key,uint32_t key_len,const uint8_t *data,uint32_t len,uint32_t deleted) {
 bridge_writes++;bridge_deleted=deleted;bridge_written_len=len;
 if(len<=16 && data)memcpy(bridge_value,data,len);
 return bridge_mode==6 ? 8 : 0;
}
static void bridge_release(uint64_t ctx,uint8_t *data,uint32_t len){bridge_releases++;free(data);}
static hp_ts_store_callbacks bridge_callbacks(void){hp_ts_store_callbacks c={bridge_read,bridge_write,bridge_release};return c;}
static inline int bridge_get_releases(void){return bridge_releases;}
static inline int bridge_get_writes(void){return bridge_writes;}
static inline int bridge_get_deleted(void){return bridge_deleted;}
static inline uint32_t bridge_get_written_len(void){return bridge_written_len;}
static void bridge_reset(int mode){bridge_mode=mode;bridge_releases=0;bridge_writes=0;bridge_deleted=0;bridge_written_len=0;}
*/
import "C"

func bridgeStore(mode int) *cStore {
	C.bridge_reset(C.int(mode))
	return &cStore{callbacks: C.bridge_callbacks(), context: 123}
}
func bridgeCounts() (int, int, bool, int) {
	return int(C.bridge_get_releases()), int(C.bridge_get_writes()), C.bridge_get_deleted() != 0, int(C.bridge_get_written_len())
}
