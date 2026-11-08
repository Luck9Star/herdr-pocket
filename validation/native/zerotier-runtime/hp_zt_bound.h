/* herdr-pocket private pinned-libzt boundary; numeric, network-bound TCP only. */
#ifndef HP_ZT_BOUND_H
#define HP_ZT_BOUND_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    HP_ZT_BOUND_OK = 0,
    HP_ZT_BOUND_AGAIN = 1,
    HP_ZT_BOUND_ERROR = 2,
    HP_ZT_BOUND_ROUTE = 3
};

int hp_zt_bound_open(uint64_t network, const uint8_t* ip, uint32_t length,
                     uint16_t port, int* fd, uint64_t* epoch);
int hp_zt_bound_state(int fd, uint64_t network, uint64_t epoch);
int hp_zt_bound_read(int fd, uint8_t* data, uint32_t cap, uint32_t* count);
int hp_zt_bound_write(int fd, const uint8_t* data, uint32_t length, uint32_t* count);
int hp_zt_bound_shutdown_write(int fd);
int hp_zt_bound_close(int fd);

/* Internal only, called with lwIP socket references and the core lock. */
struct netif;
struct ip_addr;

struct netif* hp_zt_route_locked(uint64_t network, const struct ip_addr* dest, struct ip_addr* source);
int hp_zt_lwip_bind(int fd, uint64_t network, const uint8_t* ip, uint32_t length, uint64_t* epoch);
int hp_zt_lwip_state(int fd, uint64_t network, uint64_t epoch);
int hp_zt_lwip_again(void);

#ifdef __cplusplus
}
#endif

#endif
