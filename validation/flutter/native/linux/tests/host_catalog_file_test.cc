#include "host_catalog_file.h"

#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cassert>
#include <cstdlib>
#include <string>

int main() {
  char temporary[] = "/tmp/herdr-catalog-test.XXXXXX";
  assert(mkdtemp(temporary));
  const std::string directory = std::string(temporary) + "/herdr-pocket.flutter";
  const std::string lock_path = directory + "/catalog.lock";
  const std::string catalog_path = directory + "/catalog.json";

  herdr::CatalogRead snapshot;
  std::string revision, next;
  const std::string payload = R"({"schemaVersion":4,"profiles":[],"pendingCreation":null})";
  assert(herdr::LoadCatalog(temporary, &snapshot) && snapshot.revision.empty() && snapshot.contents.empty());
  assert(herdr::SaveCatalog(temporary, "", payload, &revision) && revision.size() == 64);
  assert(!herdr::SaveCatalog(temporary, "", "stale writer", &next));
  assert(!herdr::SaveCatalog(temporary, revision, std::string(262145, 'x'), &next));
  assert(!herdr::SaveCatalog(temporary, revision, std::string("x\x00", 2), &next));

  const int lock = open(lock_path.c_str(), O_WRONLY);
  assert(lock >= 0 && flock(lock, LOCK_EX | LOCK_NB) == 0);
  assert(!herdr::SaveCatalog(temporary, revision, "locked writer", &next));
  assert(close(lock) == 0);
  assert(herdr::LoadCatalog(temporary, &snapshot) && snapshot.revision == revision && snapshot.contents == payload);

  struct stat info;
  assert(stat(catalog_path.c_str(), &info) == 0 && (info.st_mode & 0777) == 0600);
  assert(herdr::SaveCatalog(temporary, revision, "{}", &next) && next != revision);
  assert(!herdr::SaveCatalog(temporary, revision, payload, &revision));
  assert(unlink(catalog_path.c_str()) == 0);
  assert(symlink("missing-fixture", catalog_path.c_str()) == 0);
  assert(!herdr::LoadCatalog(temporary, &snapshot));
  assert(!herdr::SaveCatalog(temporary, "", payload, &next));
  assert(lstat(catalog_path.c_str(), &info) == 0 && S_ISLNK(info.st_mode));
  assert(unlink(catalog_path.c_str()) == 0);
  assert(unlink(lock_path.c_str()) == 0);
  assert(rmdir(directory.c_str()) == 0);
  assert(rmdir(temporary) == 0);
}
