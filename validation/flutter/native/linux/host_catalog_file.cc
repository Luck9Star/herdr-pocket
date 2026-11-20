#include "host_catalog_file.h"

#include <fcntl.h>
#include <glib.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstdio>
#include <utility>

namespace herdr {
namespace {

constexpr char kDirectory[] = "herdr-pocket.flutter";
constexpr char kCatalog[] = "catalog.json";

struct Fd {
  explicit Fd(int fd) : value(fd) {}
  Fd(const Fd&) = delete;
  Fd& operator=(const Fd&) = delete;
  ~Fd() { if (value >= 0) close(value); }
  int value;
};

bool Owned(int fd, bool directory, struct stat* info) {
  return fstat(fd, info) == 0 && info->st_uid == geteuid() &&
         (info->st_mode & 0077) == 0 &&
         (directory ? S_ISDIR(info->st_mode) : S_ISREG(info->st_mode) && info->st_nlink == 1);
}

int OpenDirectory(const char* data_home) {
  if (!data_home || !g_path_is_absolute(data_home) || g_mkdir_with_parents(data_home, 0700) != 0) return -1;
  const Fd home(open(data_home, O_RDONLY | O_DIRECTORY | O_CLOEXEC));
  if (home.value < 0 || (mkdirat(home.value, kDirectory, 0700) != 0 && errno != EEXIST)) return -1;
  return openat(home.value, kDirectory, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
}

bool ValidContents(const std::string& contents) {
  return !contents.empty() && contents.size() <= kMaxCatalogBytes &&
         g_utf8_validate(contents.data(), contents.size(), nullptr);
}

std::string Revision(const std::string& contents) {
  if (contents.empty()) return {};
  g_autofree gchar* digest = g_compute_checksum_for_data(G_CHECKSUM_SHA256,
      reinterpret_cast<const guchar*>(contents.data()), contents.size());
  return digest;
}

bool ReadLocked(int dir, CatalogRead* current) {
  const Fd file(openat(dir, kCatalog, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC));
  if (file.value < 0) {
    if (errno != ENOENT) return false;
    *current = {};
    return true;
  }
  struct stat info;
  if (!Owned(file.value, false, &info) || info.st_size <= 0 ||
      static_cast<size_t>(info.st_size) > kMaxCatalogBytes) return false;
  std::string contents;
  char buffer[8192];
  for (;;) {
    const ssize_t count = read(file.value, buffer, sizeof(buffer));
    if (count < 0 && errno == EINTR) continue;
    if (count < 0 || contents.size() + count > kMaxCatalogBytes) return false;
    if (count == 0) break;
    contents.append(buffer, count);
  }
  if (!ValidContents(contents)) return false;
  *current = {Revision(contents), std::move(contents)};
  return true;
}

template <typename Operation>
bool WithLock(const char* data_home, Operation operation) {
  const Fd dir(OpenDirectory(data_home));
  struct stat info;
  if (dir.value < 0 || !Owned(dir.value, true, &info)) return false;
  const Fd lock(openat(dir.value, "catalog.lock", O_CREAT | O_RDWR | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC, 0600));
  return lock.value >= 0 && Owned(lock.value, false, &info) &&
         flock(lock.value, LOCK_EX | LOCK_NB) == 0 && operation(dir.value);
}

bool WriteTemp(int dir, const char* name, const std::string& contents) {
  const Fd file(openat(dir, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600));
  if (file.value < 0) return false;
  size_t offset = 0;
  while (offset < contents.size()) {
    const ssize_t count = write(file.value, contents.data() + offset, contents.size() - offset);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) break;
    offset += count;
  }
  const bool replaced = offset == contents.size() && fsync(file.value) == 0 &&
                        renameat(dir, name, dir, kCatalog) == 0;
  if (!replaced) unlinkat(dir, name, 0);
  return replaced && fsync(dir) == 0;
}

}  // namespace

bool LoadCatalog(const char* data_home, CatalogRead* snapshot) {
  return WithLock(data_home, [&](int dir) { return ReadLocked(dir, snapshot); });
}

bool SaveCatalog(const char* data_home, const std::string& expected,
                 const std::string& contents, std::string* revision) {
  return WithLock(data_home, [&](int dir) {
    CatalogRead current;
    if (!ValidContents(contents) || !ReadLocked(dir, &current) || current.revision != expected) return false;
    g_autofree gchar* id = g_uuid_string_random();
    const std::string temporary = std::string(".catalog-") + id;
    if (!WriteTemp(dir, temporary.c_str(), contents)) return false;
    *revision = Revision(contents);
    return true;
  });
}

}  // namespace herdr
