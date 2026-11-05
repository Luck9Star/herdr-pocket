use std::{env, path::PathBuf, process::Command};

fn main() {
    println!("cargo:rerun-if-env-changed=HEELER_ET_LIB_DIR");
    println!("cargo:rerun-if-changed=tests/native_fixture.c");
    if env::var_os("CARGO_FEATURE_NATIVE_FIXTURE").is_some() {
        assert!(
            env::var("CARGO_CFG_UNIX").is_ok(),
            "native fixture currently requires a Unix C/pthread compiler; no Windows evidence"
        );
        let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
        let object = out.join("native_fixture.o");
        let status = Command::new("cc")
            .args([
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                "-c",
                "tests/native_fixture.c",
                "-o",
            ])
            .arg(&object)
            .status()
            .expect("C fixture compiler unavailable");
        assert!(status.success(), "C fixture compilation failed");
        let status = Command::new("ar")
            .arg("crs")
            .arg(out.join("libheeler_easytier.a"))
            .arg(object)
            .status()
            .expect("fixture archiver unavailable");
        assert!(status.success(), "C fixture archiving failed");
        println!("cargo:rustc-link-search=native={}", out.display());
        println!("cargo:rustc-link-lib=pthread");
    } else if env::var_os("CARGO_FEATURE_LINKED_EASYTIER").is_some() {
        let directory = PathBuf::from(env::var_os("HEELER_ET_LIB_DIR")
            .expect("linked-easytier requires explicit HEELER_ET_LIB_DIR; there is no library discovery or system network fallback"));
        assert!(
            directory.is_absolute() && directory.is_dir(),
            "native library directory must exist and be absolute"
        );
        println!("cargo:rustc-link-search=native={}", directory.display());
    }
}
