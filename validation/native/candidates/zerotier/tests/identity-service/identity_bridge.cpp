#include <jni.h>
#include "hp_zt.h"
#include "Utils.hpp"
#include <array>

namespace {
struct Buffer {
    std::array<uint8_t,HP_ZT_IDENTITY_BYTES> bytes{};
    ~Buffer() { ZeroTier::Utils::burn(bytes.data(),bytes.size()); }
};
void failed(JNIEnv *env) {
    if (!env->ExceptionCheck()) {
        jclass type=env->FindClass("java/lang/IllegalStateException");
        if (type) env->ThrowNew(type,"identity_fixture_failed");
    }
}
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_org_herdr_network_IdentityBridge_create(JNIEnv *env,jclass) {
    Buffer value;size_t length=0;uint64_t node_id=0;
    if (hp_zt_abi_version()!=1 || hp_zt_identity_create(value.bytes.data(),value.bytes.size(),&length,&node_id)!=HP_ZT_OK ||
        length!=HP_ZT_IDENTITY_BYTES || node_id==0 || node_id>=0x10000000000ULL) {
        failed(env);return nullptr;
    }
    jbyteArray result=env->NewByteArray(static_cast<jsize>(length));
    if (!result) return nullptr;
    env->SetByteArrayRegion(result,0,static_cast<jsize>(length),reinterpret_cast<const jbyte*>(value.bytes.data()));
    return env->ExceptionCheck() ? nullptr : result;
}
extern "C" JNIEXPORT jboolean JNICALL
Java_org_herdr_network_IdentityBridge_validateBytes(JNIEnv *env,jclass,jbyteArray input) {
    if (!input || env->GetArrayLength(input)!=HP_ZT_IDENTITY_BYTES) return JNI_FALSE;
    Buffer value;uint64_t node_id=0;
    env->GetByteArrayRegion(input,0,HP_ZT_IDENTITY_BYTES,reinterpret_cast<jbyte*>(value.bytes.data()));
    if (env->ExceptionCheck()) return JNI_FALSE;
    return hp_zt_identity_validate(value.bytes.data(),value.bytes.size(),&node_id)==HP_ZT_OK &&
        node_id>0 && node_id<0x10000000000ULL ? JNI_TRUE : JNI_FALSE;
}
