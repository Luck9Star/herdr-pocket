#include "hp_zt.h"
#include "Identity.hpp"
#include "Utils.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>

int main() {
    std::array<uint8_t,HP_ZT_IDENTITY_WORK_BYTES> first{}, second{}, altered{};
    size_t length=99; uint64_t id=99;
    assert(hp_zt_abi_version()==1);
    assert(hp_zt_identity_create(first.data(),269,&length,&id)==HP_ZT_BUFFER_TOO_SMALL);
    assert(length==0 && id==0);
    assert(hp_zt_identity_create(first.data(),first.size(),&length,&id)==HP_ZT_OK);
    assert(length==270 && id>0 && id<0x10000000000ULL);
    uint64_t checked=0;
    assert(hp_zt_identity_validate(first.data(),length,&checked)==HP_ZT_OK && checked==id);
    size_t second_length=0; uint64_t second_id=0;
    assert(hp_zt_identity_create(second.data(),second.size(),&second_length,&second_id)==HP_ZT_OK);
    assert(second_id!=id);
    for(size_t split : {size_t(142),size_t(206)}) {
        altered=first;
        std::memcpy(altered.data()+split,second.data()+split,64);
        ZeroTier::Identity old(reinterpret_cast<const char*>(altered.data()));
        assert(old.hasPrivate() && old.locallyValidate()); // Old public/address check accepts it.
        checked=99;
        assert(hp_zt_identity_validate(altered.data(),270,&checked)==HP_ZT_IDENTITY_INVALID && checked==0);
    }
    assert(hp_zt_identity_validate(first.data(),141,&checked)==HP_ZT_IDENTITY_INVALID);
    assert(hp_zt_identity_validate(first.data(),271,&checked)==HP_ZT_IDENTITY_INVALID);
    assert(hp_zt_identity_validate(first.data(),384,&checked)==HP_ZT_IDENTITY_INVALID);
    altered=first;altered[269]=0;
    assert(hp_zt_identity_validate(altered.data(),270,&checked)==HP_ZT_IDENTITY_INVALID);
    altered=first;altered[13]='G';
    assert(hp_zt_identity_validate(altered.data(),270,&checked)==HP_ZT_IDENTITY_INVALID);
    altered=first;altered[11]='1';
    assert(hp_zt_identity_validate(altered.data(),270,&checked)==HP_ZT_IDENTITY_INVALID);
    assert(hp_zt_identity_validate(nullptr,270,&checked)==HP_ZT_INVALID_ARGUMENT && checked==0);
    assert(hp_zt_identity_validate(first.data(),270,nullptr)==HP_ZT_INVALID_ARGUMENT);
    assert(hp_zt_identity_create(nullptr,270,&length,&id)==HP_ZT_INVALID_ARGUMENT && length==0 && id==0);
    ZeroTier::Utils::burn(first.data(),first.size());ZeroTier::Utils::burn(second.data(),second.size());ZeroTier::Utils::burn(altered.data(),altered.size());
    std::cout << "offline identity: generated private pair, DH-only/ED-only mismatch, public-only, malformed/length/null cases passed; no secret output\n";
}
