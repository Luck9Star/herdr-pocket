/* Test-only reader. The shared ABI exposes a public key, never the stored seed. */
#include "identity.h"
#include <stdio.h>

int main(int argc, char **argv) {
  char public_key[128] = {0};
  if (argc != 3 || hp_identity_public(argv[1], argv[2], public_key) != 0) return 1;
  return puts(public_key) == EOF;
}
