#include "host_catalog_file.h"
#ifdef HP_REAL_SERVICE
#include "identity.h"
#endif
#include <sys/wait.h>
#include <signal.h>
#include <unistd.h>
#include <cassert>
#include <cstdlib>
#include <string>

// A has published a reservation and is still creating the native key.
// B's concurrent discard must not clear that reservation.
int main() {
  char directory[] = "/tmp/herdr-pairing-race.XXXXXX";
  assert(mkdtemp(directory));
  herdr::CatalogRead snapshot;
  std::string revision;
  assert(herdr::LoadCatalog(directory, &snapshot));
  const int lease = herdr::AcquirePairingLease(directory);
  assert(lease >= 0);
#ifdef HP_REAL_SERVICE
  char handle[33] = {}; char public_key[128] = {};
  assert(hp_identity_reserve(handle) == 0);
#endif
  std::string pending = "pending-original-handle";
#ifdef HP_REAL_SERVICE
  pending = std::string("pending-") + handle;
#endif
  assert(herdr::SaveCatalog(directory, "", pending, &revision));
  int signal_pipe[2]; assert(pipe(signal_pipe) == 0);
  const pid_t child = fork(); assert(child >= 0);
  if (child == 0) {
    close(signal_pipe[0]);
    herdr::CatalogRead current; std::string next;
    const int other = herdr::AcquirePairingLease(directory);
    const bool deleted = other >= 0 && herdr::LoadCatalog(directory, &current) &&
      herdr::SaveCatalog(directory, current.revision, "no-pending", &next);
    if (other >= 0) close(other);
    const char result = deleted ? 'D' : 'B';
    assert(write(signal_pipe[1], &result, 1) == 1);
    _exit(0);
  }
  close(signal_pipe[1]); char result = 0;
  assert(read(signal_pipe[0], &result, 1) == 1);
  int status = 0; assert(waitpid(child, &status, 0) == child && WIFEXITED(status));
  assert(result == 'B');
  assert(herdr::LoadCatalog(directory, &snapshot));
  assert(snapshot.contents == pending);
#ifdef HP_REAL_SERVICE
  assert(hp_identity_create_reserved("herdr-pocket.flutter", handle, public_key) == 0);
  char verified[128] = {};
  assert(hp_identity_public("herdr-pocket.flutter", handle, verified) == 0);
  assert(std::string(verified) == public_key);
#endif
  close(lease);
  const int retry = herdr::AcquirePairingLease(directory);
  assert(retry >= 0); close(retry);
  int crash_ready[2]; assert(pipe(crash_ready) == 0);
  const pid_t crashed = fork(); assert(crashed >= 0);
  if (crashed == 0) {
    close(crash_ready[0]); const int held = herdr::AcquirePairingLease(directory); assert(held >= 0);
    assert(write(crash_ready[1], "R", 1) == 1); for (;;) pause();
  }
  close(crash_ready[1]); char ready = 0; assert(read(crash_ready[0], &ready, 1) == 1 && ready == 'R');
  assert(kill(crashed, SIGKILL) == 0);
  assert(waitpid(crashed, &status, 0) == crashed && WIFSIGNALED(status));
  const int after_crash = herdr::AcquirePairingLease(directory); assert(after_crash >= 0);
  assert(herdr::LoadCatalog(directory, &snapshot) && snapshot.contents == pending);
#ifdef HP_REAL_SERVICE
  char after_restart[128] = {};
  assert(hp_identity_public("herdr-pocket.flutter", handle, after_restart) == 0);
  assert(std::string(after_restart) == public_key);
  assert(hp_identity_delete("herdr-pocket.flutter", handle) == 0);
#endif
  close(after_crash);
  assert(unlink((std::string(directory) + "/herdr-pocket.flutter/catalog.json").c_str()) == 0);
  assert(unlink((std::string(directory) + "/herdr-pocket.flutter/catalog.lock").c_str()) == 0);
  assert(unlink((std::string(directory) + "/herdr-pocket.flutter/pairing.lock").c_str()) == 0);
  assert(rmdir((std::string(directory) + "/herdr-pocket.flutter").c_str()) == 0);
  assert(rmdir(directory) == 0);
}
