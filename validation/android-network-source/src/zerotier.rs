//! ZeroTier native-only Android identity bridge. The host owns library loading.
//! Java and Rust retain each device lease until exact native retirement.
use jni::{
    JNIEnv,
    objects::{GlobalRef, JByteArray, JClass, JObject, JString, JValue},
    sys::{jboolean, jbyteArray, jint, jlong},
};
use overlay_runtime::Failure;
use std::{
    collections::HashMap,
    panic::{AssertUnwindSafe, catch_unwind},
    ptr,
    sync::{
        Arc, Mutex, OnceLock,
        atomic::{AtomicBool, AtomicI32, AtomicU64, Ordering},
    },
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

const IDENTITY_BYTES: usize = 270;
const NATIVE_OK: i32 = 0;
const NATIVE_IDENTITY_INVALID: i32 = 3;
const MANAGED_NATIVE: i32 = 5;
const MANAGED_STALE: i32 = 2;
#[cfg(feature = "jvm-fixture")]
pub static FIXTURE_FAIL_AFTER_ACQUIRE: AtomicBool = AtomicBool::new(false);
#[cfg(feature = "jvm-fixture")]
pub static FIXTURE_FAIL_BEFORE_NATIVE: AtomicBool = AtomicBool::new(false);

#[cfg_attr(not(feature = "jvm-fixture"), link(name = "hp_zerotier"))]
unsafe extern "C" {
    fn hp_zt_identity_create(
        out: *mut u8,
        capacity: usize,
        len: *mut usize,
        node_id: *mut u64,
    ) -> i32;
    fn hp_zt_identity_validate(input: *const u8, len: usize, node_id: *mut u64) -> i32;
    fn hp_zt_device_new(input: *const u8, len: usize, ms: u32, owner: *mut u64) -> i32;
    fn hp_zt_device_start(owner: u64, ms: u32) -> i32;
    fn hp_zt_device_stop(owner: u64, ms: u32) -> i32;
    fn hp_zt_device_release(owner: u64, ms: u32) -> i32;
    fn hp_zt_manager_abi_version() -> u32;
}

// The entry is installed before crossing into Java or invoking the engine.
// Neither JNI exceptions nor dropping a Rust future remove the reservation.
struct Entry {
    handle: String,
    details: Mutex<Details>,
    owner: AtomicU64,
    acquire_entered: AtomicBool,
    acquire_settled: AtomicBool,
    initialize_settled: AtomicBool,
    init_entered: AtomicBool,
    native_dispatched: AtomicBool,
    init_finished: AtomicBool,
    init_result: AtomicI32,
    closing: AtomicBool,
    retiring: AtomicBool,
    ready: AtomicBool,
    retired: AtomicBool,
    bridge: Arc<Bridge>,
}
struct Details {
    instance: String,
    lease: String,
    lease_object: Option<GlobalRef>,
}
struct Registry {
    next: u64,
    entries: HashMap<u64, Arc<Entry>>,
    sessions: HashMap<u64, Arc<Entry>>,
    creating: bool,
}
static REGISTRY: OnceLock<Mutex<Registry>> = OnceLock::new();
fn registry() -> &'static Mutex<Registry> {
    REGISTRY.get_or_init(|| {
        Mutex::new(Registry {
            next: 1,
            entries: HashMap::new(),
            sessions: HashMap::new(),
            creating: false,
        })
    })
}
fn entry(reference: u64) -> Option<Arc<Entry>> {
    registry().lock().ok()?.entries.get(&reference).cloned()
}

struct Bridge {
    vm: jni::JavaVM,
    application: GlobalRef,
    class: GlobalRef,
    store: GlobalRef,
}
static BRIDGE: OnceLock<Arc<Bridge>> = OnceLock::new();
static BIND_GATE: Mutex<()> = Mutex::new(());
const STORE_CLASS: &str = "Lorg/herdr/network/AndroidZeroTierDeviceStore;";
const LEASE_CLASS: &str = "Lorg/herdr/network/AndroidZeroTierDeviceStore$RuntimeLease;";

/// Called on the application's class-loader thread, after explicitly loading
/// both native libraries. A different VM, application or class cannot replace it.
pub fn bind_zerotier(env: &mut JNIEnv<'_>, class: JClass<'_>, context: JObject<'_>) -> bool {
    let result = catch_unwind(AssertUnwindSafe(|| -> jni::errors::Result<()> {
        let _gate = BIND_GATE
            .lock()
            .map_err(|_| jni::errors::Error::NullPtr("binding"))?;
        if class.is_null() || context.is_null() {
            return Err(jni::errors::Error::NullPtr("binding"));
        }
        let app = env
            .call_method(
                context,
                "getApplicationContext",
                "()Landroid/content/Context;",
                &[],
            )?
            .l()?;
        if app.is_null() {
            return Err(jni::errors::Error::NullPtr("application"));
        }
        if let Some(previous) = BRIDGE.get() {
            if previous.vm.get_java_vm_pointer() != env.get_java_vm()?.get_java_vm_pointer()
                || !env.is_same_object(previous.application.as_obj(), &app)?
                || !env.is_same_object(previous.class.as_obj(), &class)?
            {
                return Err(jni::errors::Error::NullPtr("binding changed"));
            }
            return Ok(());
        }
        // SAFETY: ABI function is provided by the explicitly linked fixed library.
        if unsafe { hp_zt_manager_abi_version() } != 1 {
            return Err(jni::errors::Error::NullPtr("native ABI"));
        }
        env.get_static_method_id(&class, "initialize", format!("({LEASE_CLASS}JI)I"))?;
        let store = env
            .call_static_method(
                &class,
                "createStore",
                format!("(Landroid/content/Context;){STORE_CLASS}"),
                &[JValue::Object(&app)],
            )?
            .l()?;
        if store.is_null() {
            return Err(jni::errors::Error::NullPtr("store"));
        }
        let bridge = Arc::new(Bridge {
            vm: env.get_java_vm()?,
            application: env.new_global_ref(&app)?,
            class: env.new_global_ref(&class)?,
            store: env.new_global_ref(&store)?,
        });
        BRIDGE
            .set(bridge)
            .map_err(|_| jni::errors::Error::NullPtr("binding"))?;
        Ok(())
    }));
    let pending = env.exception_check().unwrap_or(true);
    if pending {
        let _ = env.exception_clear();
    }
    !pending && matches!(result, Ok(Ok(())))
}
pub fn is_zerotier_initialized() -> bool {
    BRIDGE.get().is_some()
}

fn timeout_ms(deadline: Instant) -> Result<u32, Failure> {
    let left = deadline.saturating_duration_since(Instant::now());
    if left.is_zero() {
        return Err(Failure::WaitTimeout);
    }
    Ok(left.as_nanos().div_ceil(1_000_000).min(60_000) as u32)
}
fn next_id(registry: &mut Registry) -> Result<u64, Failure> {
    if registry.next == 0 || registry.next >= i64::MAX as u64 {
        return Err(Failure::Capacity);
    }
    let id = registry.next;
    registry.next += 1;
    Ok(id)
}

/// Exact per-profile reservation. Drop intentionally does not retire it.
pub struct AndroidZeroTierReservation {
    id: u64,
    entry: Arc<Entry>,
}
impl AndroidZeroTierReservation {
    pub fn identity_ref(&self) -> &str {
        &self.entry.handle
    }
    pub fn owner(&self) -> u64 {
        self.entry.owner.load(Ordering::SeqCst)
    }
    pub fn retire_after_network(&self, deadline: Duration) -> Result<(), Failure> {
        retire(self.id, &self.entry, deadline)
    }
}

fn map_native(code: i32) -> Failure {
    if code == 4 {
        Failure::WaitTimeout
    } else {
        Failure::NativeRejected(code)
    }
}

fn capture_lease(
    env: &mut JNIEnv<'_>,
    device: &Entry,
    lease: &JObject<'_>,
) -> jni::errors::Result<()> {
    let held = env.new_global_ref(lease)?;
    // Retain the capability before extracting metadata: JNI metadata access can
    // fail, in which case a later retirement retries from this original object.
    device
        .details
        .lock()
        .map_err(|_| jni::errors::Error::NullPtr("metadata"))?
        .lease_object = Some(held);
    let meta = env
        .call_method(
            lease,
            "device",
            "()Lorg/herdr/network/AndroidZeroTierDeviceStore$Device;",
            &[],
        )?
        .l()?;
    if meta.is_null() {
        return Err(jni::errors::Error::NullPtr("device"));
    }
    let got_handle = env.get_field(&meta, "handle", "Ljava/lang/String;")?.l()?;
    let instance = env
        .get_field(&meta, "instanceId", "Ljava/lang/String;")?
        .l()?;
    let lease_id = env
        .call_method(lease, "leaseId", "()Ljava/lang/String;", &[])?
        .l()?;
    if got_handle.is_null() || instance.is_null() || lease_id.is_null() {
        return Err(jni::errors::Error::NullPtr("device metadata"));
    }
    let got_handle: String = env.get_string(&JString::from(got_handle))?.into();
    let instance: String = env.get_string(&JString::from(instance))?.into();
    let lease_id: String = env.get_string(&JString::from(lease_id))?.into();
    if got_handle != device.handle {
        return Err(jni::errors::Error::NullPtr("device changed"));
    }
    let mut details = device
        .details
        .lock()
        .map_err(|_| jni::errors::Error::NullPtr("metadata"))?;
    details.instance = instance;
    details.lease = lease_id;
    Ok(())
}

/// Obtain a profile reservation on the one process-global device. Errors after
/// the reservation exists are returned inside the tuple, so callers can retain
/// and explicitly retire the original attempt. Concurrent creation is bounded:
/// contenders receive Busy rather than waiting behind native initialization.
pub fn acquire_device(
    handle: &str,
    deadline: Duration,
) -> Result<(Arc<AndroidZeroTierReservation>, Option<Failure>), Failure> {
    if deadline.is_zero() || deadline > Duration::from_secs(60) {
        return Err(Failure::InvalidDeadline);
    }
    let bridge = BRIDGE.get().cloned().ok_or(Failure::ProviderUnavailable)?;
    let bytes = handle.as_bytes();
    if bytes.len() != 36
        || !bytes.iter().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => *c == b'-',
            14 => *c == b'4',
            19 => matches!(*c, b'8' | b'9' | b'a' | b'b'),
            _ => c.is_ascii_digit() || (b'a'..=b'f').contains(c),
        })
    {
        return Err(Failure::InvalidRoute);
    }
    let end = Instant::now() + deadline;
    let (reference, session, device) = {
        let mut guard = registry().lock().map_err(|_| Failure::WorkerUnavailable)?;
        if Instant::now() >= end {
            return Err(Failure::WaitTimeout);
        }
        if guard.creating {
            return Err(Failure::Busy);
        }
        if guard.sessions.len() >= 32 {
            return Err(Failure::Capacity);
        }
        if let Some(existing) = guard.entries.values().next().cloned() {
            if existing.handle != handle
                || existing.closing.load(Ordering::SeqCst)
                || !existing.ready.load(Ordering::SeqCst)
            {
                return Err(Failure::Busy);
            }
            let session = next_id(&mut guard)?;
            guard.sessions.insert(session, existing.clone());
            return Ok((
                Arc::new(AndroidZeroTierReservation {
                    id: session,
                    entry: existing,
                }),
                None,
            ));
        }
        let reference = next_id(&mut guard)?;
        let session = next_id(&mut guard)?;
        let device = Arc::new(Entry {
            handle: handle.to_owned(),
            details: Mutex::new(Details {
                instance: String::new(),
                lease: String::new(),
                lease_object: None,
            }),
            owner: AtomicU64::new(0),
            acquire_entered: AtomicBool::new(false),
            acquire_settled: AtomicBool::new(false),
            initialize_settled: AtomicBool::new(false),
            init_entered: AtomicBool::new(false),
            native_dispatched: AtomicBool::new(false),
            init_finished: AtomicBool::new(false),
            init_result: AtomicI32::new(MANAGED_NATIVE),
            closing: AtomicBool::new(false),
            retiring: AtomicBool::new(false),
            ready: AtomicBool::new(false),
            retired: AtomicBool::new(false),
            bridge,
        });
        guard.creating = true;
        guard.entries.insert(reference, device.clone());
        guard.sessions.insert(session, device.clone());
        (reference, session, device)
    };
    let reservation = Arc::new(AndroidZeroTierReservation {
        id: session,
        entry: device.clone(),
    });
    let mut failure = None;
    let executed = catch_unwind(AssertUnwindSafe(|| -> Result<(), Failure> {
        let mut env = device
            .bridge
            .vm
            .attach_current_thread()
            .map_err(|_| Failure::IdentityUnavailable)?;
        let result = env.with_local_frame(32, |env| -> jni::errors::Result<i32> {
            let class: &JClass<'_> = device.bridge.class.as_obj().into();
            let handle = env.new_string(&device.handle)?;
            device.acquire_entered.store(true, Ordering::SeqCst);
            let acquired = env.call_static_method(
                class,
                "acquireRetained",
                format!("({STORE_CLASS}Ljava/lang/String;){LEASE_CLASS}"),
                &[
                    JValue::Object(device.bridge.store.as_obj()),
                    JValue::Object(&handle),
                ],
            );
            device.acquire_settled.store(true, Ordering::SeqCst);
            let lease = acquired?.l()?;
            if lease.is_null() {
                return Err(jni::errors::Error::NullPtr("lease"));
            }
            #[cfg(feature = "jvm-fixture")]
            if FIXTURE_FAIL_AFTER_ACQUIRE.load(Ordering::SeqCst) {
                let _ = env.get_field(&lease, "fixtureMissingField", "I")?;
                return Err(jni::errors::Error::NullPtr("synthetic metadata failure"));
            }
            capture_lease(env, &device, &lease)?;
            let ms = timeout_ms(end).map_err(|_| jni::errors::Error::NullPtr("deadline"))?;
            env.call_static_method(
                class,
                "initialize",
                format!("({LEASE_CLASS}JI)I"),
                &[
                    JValue::Object(&lease),
                    JValue::Long(reference as i64),
                    JValue::Int(ms as i32),
                ],
            )?
            .i()
        });
        if env.exception_check().unwrap_or(true) {
            let _ = env.exception_clear();
            return Err(Failure::IdentityUnavailable);
        }
        let result = result.map_err(|_| Failure::IdentityUnavailable)?;
        if result != 0 {
            return Err(map_native(result));
        }
        let owner = device.owner.load(Ordering::SeqCst);
        if owner == 0 || !device.init_finished.load(Ordering::SeqCst) {
            return Err(Failure::InvalidNativeResponse);
        }
        let ms = timeout_ms(end)?;
        // SAFETY: this reservation exclusively retains the manager owner.
        let result = unsafe { hp_zt_device_start(owner, ms) };
        if result != 0 {
            return Err(map_native(result));
        }
        if Instant::now() >= end {
            return Err(Failure::WaitTimeout);
        }
        Ok(())
    }));
    device.initialize_settled.store(true, Ordering::SeqCst);
    match executed {
        Ok(Ok(())) => device.ready.store(true, Ordering::SeqCst),
        Ok(Err(error)) => {
            device.closing.store(true, Ordering::SeqCst);
            failure = Some(error);
        }
        Err(_) => {
            device.closing.store(true, Ordering::SeqCst);
            failure = Some(Failure::WorkerUnavailable);
        }
    }
    if let Ok(mut guard) = registry().lock() {
        guard.creating = false;
    }
    Ok((reservation, failure))
}

fn retire(id: u64, device: &Arc<Entry>, deadline: Duration) -> Result<(), Failure> {
    if deadline.is_zero() || deadline > Duration::from_secs(60) {
        return Err(Failure::InvalidDeadline);
    }
    let end = Instant::now() + deadline;
    {
        let mut guard = registry().lock().map_err(|_| Failure::WorkerUnavailable)?;
        let Some(found) = guard.sessions.get(&id) else {
            return Err(Failure::WrongOwner);
        };
        if !Arc::ptr_eq(found, device) {
            return Err(Failure::WrongOwner);
        }
        if guard
            .sessions
            .values()
            .filter(|item| Arc::ptr_eq(item, device))
            .count()
            > 1
        {
            guard.sessions.remove(&id);
            return Ok(());
        }
        device.closing.store(true, Ordering::SeqCst);
        if device.retiring.swap(true, Ordering::SeqCst) {
            return Err(Failure::Busy);
        }
    }
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<(), Failure> {
        if !device.initialize_settled.load(Ordering::SeqCst) {
            return Err(Failure::ClosePending);
        }
        let entered = device.acquire_entered.load(Ordering::SeqCst);
        if entered && !device.acquire_settled.load(Ordering::SeqCst) {
            return Err(Failure::ClosePending);
        }
        let mut held = None;
        if entered {
            let mut env = device
                .bridge
                .vm
                .attach_current_thread()
                .map_err(|_| Failure::IdentityUnavailable)?;
            let recovered =
                env.with_local_frame(16, |env| -> jni::errors::Result<Option<GlobalRef>> {
                    let class: &JClass<'_> = device.bridge.class.as_obj().into();
                    let handle = env.new_string(&device.handle)?;
                    let lease = env
                        .call_static_method(
                            class,
                            "recoverRetained",
                            format!("(Ljava/lang/String;){LEASE_CLASS}"),
                            &[JValue::Object(&handle)],
                        )?
                        .l()?;
                    if lease.is_null() {
                        return Ok(None);
                    }
                    capture_lease(env, device, &lease)?;
                    Ok(Some(env.new_global_ref(&lease)?))
                });
            if env.exception_check().unwrap_or(true) {
                let _ = env.exception_clear();
                return Err(Failure::IdentityUnavailable);
            }
            held = recovered.map_err(|_| Failure::IdentityUnavailable)?;
        }
        if held.is_none() && device.native_dispatched.load(Ordering::SeqCst) {
            return Err(Failure::ClosePending);
        }
        if let Some(held) = held {
            if !device.retired.load(Ordering::SeqCst) {
                if device.native_dispatched.load(Ordering::SeqCst) {
                    if !device.init_finished.load(Ordering::SeqCst) {
                        return Err(Failure::ClosePending);
                    }
                    let owner = device.owner.load(Ordering::SeqCst);
                    if owner == 0 && device.init_result.load(Ordering::SeqCst) == 0 {
                        return Err(Failure::InvalidNativeResponse);
                    }
                    if owner != 0 {
                        let ms = timeout_ms(end)?;
                        // SAFETY: the exact owner is retained by this reservation.
                        let stopped = unsafe { hp_zt_device_stop(owner, ms) };
                        if stopped != 0 {
                            return Err(map_native(stopped));
                        }
                        let ms = timeout_ms(end)?;
                        // SAFETY: native stop reported success for the same owner.
                        let released = unsafe { hp_zt_device_release(owner, ms) };
                        if released != 0 {
                            return Err(map_native(released));
                        }
                    }
                }
                // The callback never entered, or its original call returned with
                // no owner, or the exact manager owner has stopped and released.
                device.retired.store(true, Ordering::SeqCst);
            }
            let mut env = device
                .bridge
                .vm
                .attach_current_thread()
                .map_err(|_| Failure::IdentityUnavailable)?;
            let called = env.with_local_frame(8, |env| -> jni::errors::Result<()> {
                let class: &JClass<'_> = device.bridge.class.as_obj().into();
                env.call_static_method(
                    class,
                    "confirmAndClear",
                    format!("({LEASE_CLASS})V"),
                    &[JValue::Object(held.as_obj())],
                )?
                .v()
            });
            if env.exception_check().unwrap_or(true) {
                let _ = env.exception_clear();
                return Err(Failure::IdentityUnavailable);
            }
            called.map_err(|_| Failure::IdentityUnavailable)?;
        }
        let mut guard = registry().lock().map_err(|_| Failure::WorkerUnavailable)?;
        if !guard
            .sessions
            .get(&id)
            .is_some_and(|item| Arc::ptr_eq(item, device))
        {
            return Err(Failure::WrongOwner);
        }
        guard.sessions.remove(&id);
        guard.entries.retain(|_, item| !Arc::ptr_eq(item, device));
        Ok(())
    }))
    .unwrap_or(Err(Failure::WorkerUnavailable));
    device.retiring.store(false, Ordering::SeqCst);
    result
}

fn throw_unavailable(env: &mut JNIEnv<'_>) {
    if !env.exception_check().unwrap_or(true) {
        let _ = env.throw_new(
            "java/lang/IllegalStateException",
            "native identity unavailable",
        );
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidZeroTierNative_bindNative(
    mut env: JNIEnv<'_>,
    class: JClass<'_>,
    context: JObject<'_>,
) -> jboolean {
    u8::from(bind_zerotier(&mut env, class, context)) as jboolean
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidZeroTierNative_identityCreate(
    mut env: JNIEnv<'_>,
    _class: JClass<'_>,
) -> jbyteArray {
    let value = catch_unwind(AssertUnwindSafe(|| -> jni::errors::Result<jbyteArray> {
        let mut secret = Zeroizing::new([0_u8; IDENTITY_BYTES]);
        let mut length = 0_usize;
        let mut id = 0_u64;
        // SAFETY: buffers and output pointers are valid for this synchronous call.
        let result = unsafe {
            hp_zt_identity_create(secret.as_mut_ptr(), secret.len(), &mut length, &mut id)
        };
        if result != NATIVE_OK || length != IDENTITY_BYTES || id == 0 {
            return Err(jni::errors::Error::NullPtr("identity unavailable"));
        }
        Ok(env.byte_array_from_slice(secret.as_slice())?.into_raw())
    }));
    match value {
        Ok(Ok(array)) => array,
        _ => {
            throw_unavailable(&mut env);
            ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidZeroTierNative_identityValidate(
    mut env: JNIEnv<'_>,
    _class: JClass<'_>,
    input: JByteArray<'_>,
) -> jboolean {
    let value = catch_unwind(AssertUnwindSafe(|| -> jni::errors::Result<bool> {
        if input.is_null() || env.get_array_length(&input)? as usize != IDENTITY_BYTES {
            return Ok(false);
        }
        let secret = Zeroizing::new(env.convert_byte_array(&input)?);
        let mut id = 0_u64;
        // SAFETY: secret remains live for the entire synchronous validation.
        let result = unsafe { hp_zt_identity_validate(secret.as_ptr(), secret.len(), &mut id) };
        match result {
            NATIVE_OK if id != 0 => Ok(true),
            NATIVE_IDENTITY_INVALID => Ok(false),
            _ => Err(jni::errors::Error::NullPtr("identity unavailable")),
        }
    }));
    match value {
        Ok(Ok(valid)) => u8::from(valid),
        _ => {
            throw_unavailable(&mut env);
            0
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidZeroTierNative_initializeDevice(
    mut env: JNIEnv<'_>,
    _class: JClass<'_>,
    reference: jlong,
    input: JByteArray<'_>,
    timeout: jint,
) -> jint {
    let value = catch_unwind(AssertUnwindSafe(|| -> jni::errors::Result<i32> {
        let Some(device) = u64::try_from(reference).ok().and_then(entry) else {
            return Ok(MANAGED_STALE);
        };
        if input.is_null()
            || timeout <= 0
            || timeout > 60000
            || env.get_array_length(&input)? as usize != IDENTITY_BYTES
            || device.init_entered.swap(true, Ordering::SeqCst)
        {
            return Ok(MANAGED_NATIVE);
        }
        #[cfg(feature = "jvm-fixture")]
        if FIXTURE_FAIL_BEFORE_NATIVE.load(Ordering::SeqCst) {
            let _ = env.get_field(&input, "fixtureMissingField", "I")?;
            return Err(jni::errors::Error::NullPtr("synthetic conversion failure"));
        }
        let secret = Zeroizing::new(env.convert_byte_array(&input)?);
        let mut owner = 0_u64;
        device.native_dispatched.store(true, Ordering::SeqCst);
        // SAFETY: original Java callback and this zeroizing copy outlive this call.
        let result =
            unsafe { hp_zt_device_new(secret.as_ptr(), secret.len(), timeout as u32, &mut owner) };
        device.owner.store(owner, Ordering::SeqCst);
        device.init_result.store(result, Ordering::SeqCst);
        device.init_finished.store(true, Ordering::SeqCst);
        Ok(result)
    }));
    match value {
        Ok(Ok(result)) => result,
        _ => {
            throw_unavailable(&mut env);
            MANAGED_NATIVE
        }
    }
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_org_herdr_network_AndroidZeroTierNative_retiredExactly(
    mut env: JNIEnv<'_>,
    _class: JClass<'_>,
    handle: JObject<'_>,
    instance: JObject<'_>,
    lease: JObject<'_>,
) -> jboolean {
    let value = catch_unwind(AssertUnwindSafe(|| -> jni::errors::Result<bool> {
        use jni::objects::JString;
        if handle.is_null() || instance.is_null() || lease.is_null() {
            return Ok(false);
        }
        let handle: String = env.get_string(&JString::from(handle))?.into();
        let instance: String = env.get_string(&JString::from(instance))?.into();
        let lease: String = env.get_string(&JString::from(lease))?.into();
        let guard = registry()
            .lock()
            .map_err(|_| jni::errors::Error::NullPtr("registry"))?;
        Ok(guard.entries.values().any(|e| {
            if !e.retired.load(Ordering::SeqCst) || e.handle != handle {
                return false;
            }
            e.details
                .lock()
                .map(|d| d.instance == instance && d.lease == lease)
                .unwrap_or(false)
        }))
    }));
    match value {
        Ok(Ok(valid)) => u8::from(valid),
        _ => {
            throw_unavailable(&mut env);
            0
        }
    }
}
