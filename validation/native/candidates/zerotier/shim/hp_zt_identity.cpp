/* herdr-pocket offline identity adapter. Uses the pinned ZeroTierOne identity
 * implementation; no libzt globals, node start, storage path, socket or callback.
 */
#include "hp_zt.h"
#include "Identity.hpp"
#include "ECC.hpp"
#include "Utils.hpp"
#include <cstring>
#include <cstdint>
#include <algorithm>

namespace {
using namespace ZeroTier;
static_assert(ZT_IDENTITY_STRING_BUFFER_LENGTH == HP_ZT_IDENTITY_WORK_BYTES, "identity ABI changed");
static_assert(ZT_ECC_PUBLIC_KEY_SET_LEN == 64 && ZT_ECC_PRIVATE_KEY_SET_LEN == 64, "type-0 ECC only");
template<class T> struct Wipe {T &value; ~Wipe(){Utils::burn(&value, sizeof(value));}};
bool lower_hex(uint8_t byte){return (byte >= '0' && byte <= '9') || (byte >= 'a' && byte <= 'f');}
uint8_t nibble(uint8_t byte){return byte <= '9' ? byte-'0' : byte-'a'+10;}
void decode(const uint8_t *bytes,uint8_t *output,size_t count){for(size_t i=0;i<count;++i)output[i]=uint8_t((nibble(bytes[i*2])<<4)|nibble(bytes[i*2+1]));}
int validate(const uint8_t *bytes,size_t length,uint64_t *node_id){
    if(length!=HP_ZT_IDENTITY_BYTES) { return HP_ZT_IDENTITY_INVALID; }
    for(size_t i=0;i<length;++i){
        if(i==10 || i==12 || i==141){if(bytes[i]!=':') { return HP_ZT_IDENTITY_INVALID; }}
        else if(i==11){if(bytes[i]!='0') { return HP_ZT_IDENTITY_INVALID; }}
        else if(!lower_hex(bytes[i])) { return HP_ZT_IDENTITY_INVALID; }
    }
    char text[HP_ZT_IDENTITY_WORK_BYTES]={0};Wipe<decltype(text)> wipe_text{text};
    std::memcpy(text,bytes,length);
    Identity identity;
    if(!identity.fromString(text) || !identity.hasPrivate() || !identity.locallyValidate()) { return HP_ZT_IDENTITY_INVALID; }
    ECC::Private secret{};Wipe<ECC::Private> wipe_secret{secret};
    ECC::Public expected{};decode(bytes+13,expected.data,64);decode(bytes+142,secret.data,64);
    const ECC::Public derived=ECC::derivePublic(secret);
    uint8_t mismatch=0;for(size_t i=0;i<64;++i)mismatch|=derived.data[i]^expected.data[i];
    if(mismatch) { return HP_ZT_IDENTITY_INVALID; }
    // Reject noncanonical encodings accepted by the upstream parser.
    char canonical[HP_ZT_IDENTITY_WORK_BYTES]={0};Wipe<decltype(canonical)> wipe_canonical{canonical};
    identity.toString(true,canonical);
    if(std::strlen(canonical)!=length || std::memcmp(canonical,bytes,length)) { return HP_ZT_IDENTITY_INVALID; }
    *node_id=identity.address().toInt();return HP_ZT_OK;
}
}
extern "C" uint32_t hp_zt_abi_version(void){return HP_ZT_ABI_VERSION;}
extern "C" int hp_zt_identity_validate(const uint8_t *identity,size_t length,uint64_t *node_id){
    if(node_id) { *node_id=0; }
    if(!identity || !node_id) { return HP_ZT_INVALID_ARGUMENT; }
    try{return validate(identity,length,node_id);}catch(...){*node_id=0;return HP_ZT_UNAVAILABLE;}
}
extern "C" int hp_zt_identity_create(uint8_t *output,size_t capacity,size_t *output_length,uint64_t *node_id){
    if(output_length) { *output_length=0; }if(node_id) { *node_id=0; }
    if(!output || !output_length || !node_id) { return HP_ZT_INVALID_ARGUMENT; }
    if(capacity<HP_ZT_IDENTITY_BYTES) { return HP_ZT_BUFFER_TOO_SMALL; }
    try{
        Identity identity;identity.generate();
        char text[HP_ZT_IDENTITY_WORK_BYTES]={0};Wipe<decltype(text)> wipe_text{text};identity.toString(true,text);
        uint64_t checked=0;const int result=validate(reinterpret_cast<const uint8_t *>(text),std::strlen(text),&checked);
        if(result!=HP_ZT_OK) { return result; }
        std::memcpy(output,text,HP_ZT_IDENTITY_BYTES);*output_length=HP_ZT_IDENTITY_BYTES;*node_id=checked;return HP_ZT_OK;
    }catch(...){ZeroTier::Utils::burn(output,HP_ZT_IDENTITY_BYTES);return HP_ZT_UNAVAILABLE;}
}
