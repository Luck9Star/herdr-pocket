// Offline-only access to the actual ECC.cpp static field helpers. This does not
// install a new public crypto API. All inputs come from the public test corpus.
#include "ECC.cpp"
#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>

namespace {
bool bytes(std::istream& in, unsigned char* out, size_t length) {
    std::string value;
    if (!(in >> value) || value.size() != length * 2) { return false; }
    for (size_t i = 0; i < length; ++i) {
        const auto digit = [](char c) -> int {
            if (c >= '0' && c <= '9') { return c - '0'; }
            if (c >= 'a' && c <= 'f') { return c - 'a' + 10; }
            return -1;
        };
        const int high = digit(value[2*i]), low = digit(value[2*i+1]);
        if (high < 0 || low < 0) { return false; }
        out[i] = static_cast<unsigned char>(high * 16 + low);
    }
    return true;
}
void hex(const unsigned char* value, size_t length) {
    const char* digits = "0123456789abcdef";
    for (size_t i = 0; i < length; ++i) {
        std::cout << digits[value[i] >> 4] << digits[value[i] & 15];
    }
    std::cout << '\n';
}
bool limbs(std::istream& in, limb* value, size_t length) {
    for (size_t i = 0; i < length; ++i) {
        if (!(in >> value[i])) { return false; }
    }
    return true;
}
}

int main() {
    std::string operation;
    while (std::cin >> operation) {
        if (operation == "eq") {
            int64_t a, b;
            if (!(std::cin >> a >> b) || a < INT32_MIN || a > INT32_MAX ||
                b < INT32_MIN || b > INT32_MAX) { return 2; }
            std::cout << s32_eq(static_cast<s32>(a), static_cast<s32>(b)) << '\n';
        } else if (operation == "reduce") {
            limb value[19] = {};
            if (!limbs(std::cin, value, 19)) { return 2; }
            freduce_degree(value);
            freduce_coefficients(value);
            for (size_t i = 0; i < 10; ++i) { std::cout << value[i] << (i == 9 ? '\n' : ' '); }
        } else if (operation == "coeff") {
            limb value[11] = {};
            if (!limbs(std::cin, value, 10)) { return 2; }
            freduce_coefficients(value);
            for (size_t i = 0; i < 10; ++i) { std::cout << value[i] << (i == 9 ? '\n' : ' '); }
        } else if (operation == "contract" || operation == "mul" || operation == "square") {
            limb a[10] = {}, b[10] = {}, result[10] = {};
            unsigned char encoded[32];
            if (!limbs(std::cin, a, 10)) { return 2; }
            if (operation == "mul") {
                if (!limbs(std::cin, b, 10)) { return 2; }
                fmul(result, a, b);
            } else if (operation == "square") {
                fsquare(result, a);
            } else { std::memcpy(result, a, sizeof(result)); }
            fcontract(encoded, result);
            hex(encoded, sizeof(encoded));
        } else if (operation == "x") {
            unsigned char scalar[32], point[32], result[32];
            if (!bytes(std::cin, scalar, 32) || !bytes(std::cin, point, 32)) { return 2; }
            crypto_scalarmult(result, scalar, point);
            hex(result, sizeof(result));
            ZeroTier::Utils::burn(scalar, sizeof(scalar));
        } else if (operation == "ed") {
            // Input is a public deterministic test seed, never a device key.
            ZeroTier::ECC::Private secret = {};
            unsigned char message[32], signature[96];
            if (!bytes(std::cin, secret.data + 32, 32) || !bytes(std::cin, message, 32)) { return 2; }
            const auto pub = ZeroTier::ECC::derivePublic(secret);
            ZeroTier::ECC::sign(secret, pub, message, sizeof(message), signature);
            if (!ZeroTier::ECC::verify(pub, message, sizeof(message), signature)) { return 3; }
            hex(pub.data + 32, 32);
            hex(signature, sizeof(signature));
            signature[0] ^= 1;
            if (ZeroTier::ECC::verify(pub, message, sizeof(message), signature)) { return 3; }
            ZeroTier::Utils::burn(secret.data, sizeof(secret.data));
        } else { return 2; }
    }
    return std::cin.eof() ? 0 : 2;
}
