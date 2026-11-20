# Only the generated Linux runner includes this file.
find_program(HERDR_CARGO_EXECUTABLE cargo)
if(NOT HERDR_CARGO_EXECUTABLE)
  message(FATAL_ERROR "The Linux pairing runner needs Cargo with Rust 1.96.0")
endif()
find_package(Threads REQUIRED)
set(HERDR_IDENTITY_SOURCE "${CMAKE_CURRENT_LIST_DIR}/../herdr-secure-identity")
set(HERDR_IDENTITY_TARGET "${CMAKE_CURRENT_BINARY_DIR}/herdr-identity-target")
set(HERDR_IDENTITY_LIBRARY "${HERDR_IDENTITY_TARGET}/release/libherdr_linux_secure_identity.a")
add_custom_target(herdr_linux_identity
  COMMAND "${HERDR_CARGO_EXECUTABLE}" +1.96.0 build --locked --release
          --manifest-path "${HERDR_IDENTITY_SOURCE}/Cargo.toml"
          --target-dir "${HERDR_IDENTITY_TARGET}"
  BYPRODUCTS "${HERDR_IDENTITY_LIBRARY}"
  VERBATIM)
add_dependencies(${BINARY_NAME} herdr_linux_identity)
target_sources(${BINARY_NAME} PRIVATE pairing_channels.cc host_catalog_file.cc)
target_compile_features(${BINARY_NAME} PRIVATE cxx_std_17)
target_include_directories(${BINARY_NAME} PRIVATE "${HERDR_IDENTITY_SOURCE}")
target_link_libraries(${BINARY_NAME} PRIVATE "${HERDR_IDENTITY_LIBRARY}" util rt Threads::Threads m ${CMAKE_DL_LIBS})
