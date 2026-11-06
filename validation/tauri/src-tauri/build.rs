fn main() {
    #[cfg(target_os = "macos")]
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("ios") {
        build_ios_plugin();
    }
    #[cfg(target_os = "macos")]
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        build_macos_documents();
    }
    tauri_build::build()
}

#[cfg(target_os = "macos")]
fn build_macos_documents() {
    use std::{env, path::PathBuf, process::Command};
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    let shared = root.join("../../config-transfer/apple/ConfigDocument.swift");
    let bridge = root.join("../ios/MacDocumentBridge.swift");
    println!("cargo:rerun-if-changed={}", shared.display());
    println!("cargo:rerun-if-changed={}", bridge.display());
    let arch = match env::var("CARGO_CFG_TARGET_ARCH").as_deref() {
        Ok("aarch64") => "arm64",
        Ok("x86_64") => "x86_64",
        _ => panic!("unsupported macOS architecture"),
    };
    let result = Command::new("xcrun")
        .args([
            "swiftc",
            "-parse-as-library",
            "-emit-library",
            "-static",
            "-target",
            &format!("{arch}-apple-macosx11.0"),
            "-module-cache-path",
        ])
        .arg(out.join("swift-module-cache"))
        .arg(&shared)
        .arg(&bridge)
        .arg("-o")
        .arg(out.join("libpocket_document.a"))
        .status()
        .expect("run macOS document bridge compiler");
    assert!(result.success(), "compile macOS document bridge");
    let swiftc = Command::new("xcrun")
        .args(["--find", "swiftc"])
        .output()
        .expect("find Swift compiler");
    assert!(swiftc.status.success(), "find Swift compiler");
    let swiftc = PathBuf::from(
        String::from_utf8(swiftc.stdout)
            .expect("UTF-8 Swift path")
            .trim(),
    );
    let runtime = swiftc
        .parent()
        .and_then(|p| p.parent())
        .expect("Swift toolchain root")
        .join("lib/swift/macosx");
    assert!(
        runtime.is_dir(),
        "Swift compatibility libraries unavailable"
    );
    println!("cargo:rustc-link-search=native={}", out.display());
    println!("cargo:rustc-link-search=native={}", runtime.display());
    println!("cargo:rustc-link-search=native=/usr/lib/swift");
    println!("cargo:rustc-link-lib=static=pocket_document");
    println!("cargo:rustc-link-lib=framework=AppKit");
    println!("cargo:rustc-link-lib=framework=Foundation");
    println!("cargo:rustc-link-lib=swiftCore");
}

// Build from the shared Swift sources without modifying the generated project.
#[cfg(target_os = "macos")]
fn build_ios_plugin() {
    use std::{env, fs, path::PathBuf};
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("pocket-ios");
    let sources = out.join("Sources");
    fs::create_dir_all(&sources).expect("create iOS plugin build directory");
    for (source, name) in [
        (root.join("../ios/PocketPlugin.swift"), "PocketPlugin.swift"),
        (
            root.join("../ios/PocketKeyBridge.swift"),
            "PocketKeyBridge.swift",
        ),
        (
            root.join("../../pairing/native/apple/DeviceKeys.swift"),
            "DeviceKeys.swift",
        ),
        (
            root.join("../../pairing/native/camera/apple/PairScanner.swift"),
            "PairScanner.swift",
        ),
        (
            root.join("../../config-transfer/apple/ConfigDocument.swift"),
            "ConfigDocument.swift",
        ),
    ] {
        println!("cargo:rerun-if-changed={}", source.display());
        fs::copy(source, sources.join(name)).expect("copy shared iOS plugin source");
    }
    let api = env::var("DEP_TAURI_IOS_LIBRARY_PATH").expect("Tauri iOS API metadata missing");
    let manifest = format!(
        r#"// swift-tools-version:5.5
import PackageDescription
let package = Package(name: "HerdrPocketIOS", platforms: [.iOS(.v15)],
  products: [.library(name: "HerdrPocketIOS", type: .static, targets: ["HerdrPocketIOS"])],
  dependencies: [.package(name: "Tauri", path: {:?})],
  targets: [.target(name: "HerdrPocketIOS", dependencies: [.byName(name: "Tauri")], path: "Sources")])
"#,
        api
    );
    fs::write(out.join("Package.swift"), manifest).expect("write iOS package manifest");
    tauri_utils::build::link_apple_library("HerdrPocketIOS", out);
}
