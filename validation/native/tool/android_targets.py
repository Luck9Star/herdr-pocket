"""Explicit pinned API35 targets; host architecture never selects a device ABI."""
from pathlib import Path

API = 35
NDK = '28.2.13676358'
DEFAULT = 'arm64-v8a'
TARGETS = {
    'arm64-v8a': ('aarch64-linux-android', 'arm64', 183),
    'x86_64': ('x86_64-linux-android', 'amd64', 62),
}


def target(abi):
    if abi not in TARGETS:
        raise ValueError('unsupported Android ABI')
    return TARGETS[abi]


def tools(ndk, abi):
    ndk = Path(ndk).resolve()
    if ndk.name != NDK:
        raise ValueError('wrong pinned Android NDK')
    triple, _, _ = target(abi)
    directory = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    compiler = directory / (triple + str(API) + '-clang')
    if any(not path.is_file() for path in (compiler, Path(str(compiler) + '++'), directory / 'llvm-ar')):
        raise ValueError('existing pinned Linux Android toolchain required')
    return directory, compiler


def rust_environment(ndk, abi):
    directory, compiler = tools(ndk, abi)
    triple, _, _ = target(abi)
    key = triple.replace('-', '_')
    return {f'CC_{key}': str(compiler), f'CXX_{key}': str(compiler) + '++',
            f'AR_{key}': str(directory / 'llvm-ar'),
            f'CARGO_TARGET_{key.upper()}_LINKER': str(compiler)}
