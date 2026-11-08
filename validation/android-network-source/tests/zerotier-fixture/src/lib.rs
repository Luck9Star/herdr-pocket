//! Desktop JVM fixture only; production JNI and Java sources remain unchanged.
#[path = "../../../src/zerotier.rs"]
mod zerotier;
use jni::{
    JNIEnv,
    objects::{JClass, JObject, JString},
    sys::{jboolean, jint, jlong},
};
use std::{
    collections::HashMap,
    sync::{
        Arc, Mutex, OnceLock,
        atomic::{AtomicBool, AtomicI32, AtomicU64, Ordering},
    },
    time::Duration,
};

static SESSIONS: OnceLock<Mutex<HashMap<u64, Arc<zerotier::AndroidZeroTierReservation>>>> =
    OnceLock::new();
static NEXT: AtomicU64 = AtomicU64::new(1);
static STOP_CODE: AtomicI32 = AtomicI32::new(0);
static START_CODE: AtomicI32 = AtomicI32::new(0);
static VALIDATE_CODE: AtomicI32 = AtomicI32::new(0);
static CREATE_CODE: AtomicI32 = AtomicI32::new(0);
static INIT_BLOCK: AtomicBool = AtomicBool::new(false);
static INIT_ENTERED: AtomicBool = AtomicBool::new(false);
static ALIVE: AtomicBool = AtomicBool::new(false);
fn sessions() -> &'static Mutex<HashMap<u64, Arc<zerotier::AndroidZeroTierReservation>>> {
    SESSIONS.get_or_init(|| Mutex::new(HashMap::new()))
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn hp_zt_identity_create(
    out: *mut u8,
    cap: usize,
    len: *mut usize,
    id: *mut u64,
) -> i32 {
    if CREATE_CODE.load(Ordering::SeqCst) != 0 {
        return CREATE_CODE.load(Ordering::SeqCst);
    }
    if cap != 270 {
        return 2;
    }
    // SAFETY: the production bridge supplies writable buffers of these exact sizes.
    unsafe {
        std::ptr::write_bytes(out, b'X', 270);
        *len = 270;
        *id = 123;
    }
    0
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hp_zt_identity_validate(
    input: *const u8,
    len: usize,
    id: *mut u64,
) -> i32 {
    if VALIDATE_CODE.load(Ordering::SeqCst) != 0 {
        return VALIDATE_CODE.load(Ordering::SeqCst);
    }
    // SAFETY: the production bridge supplies a 270-byte live slice.
    if len != 270 || unsafe { *input } != b'X' {
        return 3;
    }
    unsafe {
        *id = 123;
    }
    0
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn hp_zt_device_new(
    _input: *const u8,
    len: usize,
    _ms: u32,
    owner: *mut u64,
) -> i32 {
    if len != 270 || ALIVE.swap(true, Ordering::SeqCst) {
        return 3;
    }
    INIT_ENTERED.store(true, Ordering::SeqCst);
    while INIT_BLOCK.load(Ordering::SeqCst) {
        std::thread::yield_now();
    }
    unsafe {
        *owner = 41;
    }
    0
}
#[unsafe(no_mangle)]
pub extern "C" fn hp_zt_device_start(owner: u64, _ms: u32) -> i32 {
    if owner == 41 {
        START_CODE.load(Ordering::SeqCst)
    } else {
        2
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn hp_zt_device_stop(owner: u64, _ms: u32) -> i32 {
    if owner == 41 {
        STOP_CODE.load(Ordering::SeqCst)
    } else {
        2
    }
}
#[unsafe(no_mangle)]
pub extern "C" fn hp_zt_device_release(owner: u64, _ms: u32) -> i32 {
    if owner != 41 {
        return 2;
    }
    ALIVE.store(false, Ordering::SeqCst);
    0
}
#[unsafe(no_mangle)]
pub extern "C" fn hp_zt_manager_abi_version() -> u32 {
    1
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_bind(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    let class = match env.find_class("org/herdr/network/AndroidZeroTierNative") {
        Ok(value) => value,
        Err(_) => return 0,
    };
    u8::from(
        zerotier::bind_zerotier(&mut env, class, context) && zerotier::is_zerotier_initialized(),
    )
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_acquire(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
    handle: JString<'_>,
) -> jlong {
    acquire_impl(&mut env, handle, Duration::from_secs(1))
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_acquireTimeout(
    mut env: JNIEnv<'_>,
    _: JClass<'_>,
    handle: JString<'_>,
    ms: jint,
) -> jlong {
    acquire_impl(&mut env, handle, Duration::from_millis(ms as u64))
}
fn acquire_impl(env: &mut JNIEnv<'_>, handle: JString<'_>, deadline: Duration) -> jlong {
    let handle: String = match env.get_string(&handle) {
        Ok(value) => value.into(),
        Err(_) => return 0,
    };
    let (value, failure) = match zerotier::acquire_device(&handle, deadline) {
        Ok(value) => value,
        Err(_) => return 0,
    };
    if value.identity_ref() != handle {
        return 0;
    }
    let id = NEXT.fetch_add(1, Ordering::SeqCst);
    sessions().lock().unwrap().insert(id, value);
    if failure.is_some() {
        -(id as i64)
    } else {
        id as i64
    }
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_owner(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    id: jlong,
) -> jlong {
    sessions()
        .lock()
        .unwrap()
        .get(&(id as u64))
        .map_or(0, |value| value.owner() as i64)
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_retire(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    id: jlong,
) -> jboolean {
    let value = sessions().lock().unwrap().get(&(id as u64)).cloned();
    u8::from(value.is_some_and(|value| value.retire_after_network(Duration::from_secs(1)).is_ok()))
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_stopResult(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    code: jint,
) {
    STOP_CODE.store(code, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_startResult(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    code: jint,
) {
    START_CODE.store(code, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_validatorResult(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    code: jint,
) {
    VALIDATE_CODE.store(code, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_generatorResult(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    code: jint,
) {
    CREATE_CODE.store(code, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_failMetadata(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    value: jboolean,
) {
    zerotier::FIXTURE_FAIL_AFTER_ACQUIRE.store(value != 0, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_failBeforeNative(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    value: jboolean,
) {
    zerotier::FIXTURE_FAIL_BEFORE_NATIVE.store(value != 0, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_blockInit(
    _: JNIEnv<'_>,
    _: JClass<'_>,
    block: jboolean,
) {
    INIT_ENTERED.store(false, Ordering::SeqCst);
    INIT_BLOCK.store(block != 0, Ordering::SeqCst);
}
#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_ZeroTierJniProbe_initEntered(
    _: JNIEnv<'_>,
    _: JClass<'_>,
) -> jboolean {
    u8::from(INIT_ENTERED.load(Ordering::SeqCst))
}
