#ifndef HERDR_LINUX_SECURE_IDENTITY_H
#define HERDR_LINUX_SECURE_IDENTITY_H
#include <stddef.h>
#include <stdint.h>
/* 0 success; 1 invalid input; 2 missing; 3 locked; 4 unavailable;
 * 5 write result unknown; 6 payload too large; 7 handle already exists.
 * Caller owns all buffers; no returned private material. */
int32_t hp_identity_reserve(char handle_out[33]);
int32_t hp_identity_create_reserved(const char *app, const char *handle, char public_out[128]);
int32_t hp_identity_public(const char *app, const char *handle, char public_out[128]);
int32_t hp_identity_sign(const char *app, const char *handle, const uint8_t *data, size_t length, uint8_t signature_out[64]);
int32_t hp_identity_delete(const char *app, const char *handle);
#endif
