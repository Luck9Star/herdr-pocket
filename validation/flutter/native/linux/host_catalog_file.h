#pragma once

#include <cstddef>
#include <string>

namespace herdr {

constexpr size_t kMaxCatalogBytes = 262144;

struct CatalogRead {
  std::string revision;
  std::string contents;
};

// This channel stores only public catalog metadata and opaque identity handles.
bool LoadCatalog(const char* data_home, CatalogRead* snapshot);
bool SaveCatalog(const char* data_home, const std::string& expected,
                 const std::string& contents, std::string* revision);

}  // namespace herdr
