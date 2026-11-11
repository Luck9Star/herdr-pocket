use std::{env, path::PathBuf, process::Command};

fn fixture(source: &str, library: &str) {
    assert!(
        env::var("CARGO_CFG_UNIX").is_ok(),
        "synthetic ABI fixture requires Unix C/pthread; no Windows evidence"
    );
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let object = out.join(format!("{library}.o"));
    let status = Command::new("cc")
        .args([
            "-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread", "-c", source, "-o",
        ])
        .arg(&object)
        .args(["-I", "../native/candidates/zerotier/shim"])
        .status()
        .expect("C fixture compiler unavailable");
    assert!(status.success(), "C fixture compilation failed");
    let status = Command::new("ar")
        .arg("crs")
        .arg(out.join(format!("lib{library}.a")))
        .arg(object)
        .status()
        .expect("fixture archiver unavailable");
    assert!(status.success(), "C fixture archiving failed");
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-lib=pthread");
}
fn explicit_library(variable: &str, feature: &str) {
    let directory = PathBuf::from(env::var_os(variable).unwrap_or_else(|| {
        panic!("{feature} requires explicit {variable}; no discovery or fallback")
    }));
    assert!(
        directory.is_absolute() && directory.is_dir(),
        "native library directory must exist and be absolute"
    );
    println!("cargo:rustc-link-search=native={}", directory.display());
    // iOS ships the app lib as a staticlib consumed by the Xcode link, and no
    // external search path reaches that link (proven r3-r7). Fold the provider
    // archive into the staticlib instead; rustc unpacks it during packaging.
    if variable == "HEELER_ET_LIB_DIR"
        && env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("ios")
    {
        println!("cargo:rustc-link-lib=static=heeler_easytier");
    }
}
fn main() {
    for variable in ["HEELER_ET_LIB_DIR", "HP_TS_LIB_DIR", "HP_ZT_LIB_DIR"] {
        println!("cargo:rerun-if-env-changed={variable}");
    }
    for source in [
        "tests/native_fixture.c",
        "tests/tailscale_fixture.c",
        "tests/zerotier_fixture.c",
        "../native/zerotier-runtime/hp_zt_manager.h",
        "../native/tailscale-runtime/hp_ts.h",
    ] {
        println!("cargo:rerun-if-changed={source}");
    }
    if env::var_os("CARGO_FEATURE_NATIVE_FIXTURE").is_some() {
        fixture("tests/native_fixture.c", "heeler_easytier");
    } else if env::var_os("CARGO_FEATURE_LINKED_EASYTIER").is_some() {
        explicit_library("HEELER_ET_LIB_DIR", "linked-easytier");
    }
    if env::var_os("CARGO_FEATURE_TAILSCALE_FIXTURE").is_some() {
        fixture("tests/tailscale_fixture.c", "hp_tailscale");
    } else if env::var_os("CARGO_FEATURE_LINKED_TAILSCALE").is_some() {
        explicit_library("HP_TS_LIB_DIR", "linked-tailscale");
    }
    if env::var_os("CARGO_FEATURE_ZEROTIER_FIXTURE").is_some() {
        fixture("tests/zerotier_fixture.c", "hp_zerotier");
    } else if env::var_os("CARGO_FEATURE_LINKED_ZEROTIER").is_some() {
        explicit_library("HP_ZT_LIB_DIR", "linked-zerotier");
    }
}
