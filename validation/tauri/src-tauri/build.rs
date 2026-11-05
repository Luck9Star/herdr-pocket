fn main() {
    #[cfg(target_os = "macos")]
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("ios") {
        build_ios_plugin();
    }
    tauri_build::build()
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
