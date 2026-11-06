#!/usr/bin/env python3
"""Public-vector/bigint oracle for the actual sanitized ECC.cpp driver.

No identity store, node, network, ambient crypto package or secret output. The
variable-time Python arithmetic is an offline oracle, NEVER production crypto.
X25519 follows RFC 7748 section 5; extended Edwards arithmetic/signing follows
RFC 8032 section 6 (with modular reduction after each point operation).

RFC code components: Copyright (c) 2016/2017 IETF Trust and the persons identified
as authors of RFC 7748/8032. Redistribution and use in source and binary forms,
with or without modification, are permitted provided that the following
conditions are met: (1) Redistributions of source code must retain the above
copyright notice, this list of conditions and the following disclaimer.
(2) Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation and/or
other materials provided with the distribution. (3) Neither the name of Internet
Society, IETF or IETF Trust, nor the names of specific contributors, may be used
to endorse or promote products derived from this software without specific prior
written permission. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import argparse
import hashlib
import random
import re
import subprocess

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P-2, P) % P
WEIGHTS = [2**((51*i+1)//2) for i in range(10)]


def x25519(scalar, point):
    k = bytearray(scalar)
    k[0] &= 248
    k[31] = (k[31] & 127) | 64
    k = int.from_bytes(k, 'little')
    x1 = int.from_bytes(point, 'little') & (2**255-1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in range(254, -1, -1):
        bit = (k >> t) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b = (x2+z2) % P, (x2-z2) % P
        aa, bb = a*a % P, b*b % P
        e = (aa-bb) % P
        c, d = (x3+z3) % P, (x3-z3) % P
        da, cb = d*a % P, c*b % P
        x3, z3 = (da+cb)**2 % P, x1*(da-cb)**2 % P
        x2, z2 = aa*bb % P, e*(aa+121665*e) % P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2*pow(z2, P-2, P) % P).to_bytes(32, 'little')


def point_add(a, b):
    aa = (a[1]-a[0])*(b[1]-b[0]) % P
    bb = (a[1]+a[0])*(b[1]+b[0]) % P
    cc, dd = 2*a[3]*b[3]*D % P, 2*a[2]*b[2] % P
    e, f, g, h = bb-aa, dd-cc, dd+cc, bb+aa
    return e*f % P, g*h % P, f*g % P, e*h % P


def point_mul(scalar, point):
    result = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = point_add(result, point)
        point = point_add(point, point)
        scalar >>= 1
    return result


def point_compress(point):
    inv = pow(point[2], P-2, P)
    x, y = point[0]*inv % P, point[1]*inv % P
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


_gy = 4*pow(5, P-2, P) % P
_xx = (_gy*_gy-1)*pow(D*_gy*_gy+1, P-2, P) % P
_gx = pow(_xx, (P+3)//8, P)
if (_gx*_gx-_xx) % P:
    _gx = _gx*pow(2, (P-1)//4, P) % P
if _gx & 1:
    _gx = P-_gx
BASE = (_gx, _gy, 1, _gx*_gy % P)


def ed25519(seed, message):
    h = hashlib.sha512(seed).digest()
    a = (int.from_bytes(h[:32], 'little') & (2**254-8)) | 2**254
    public = point_compress(point_mul(a, BASE))
    r = int.from_bytes(hashlib.sha512(h[32:]+message).digest(), 'little') % Q
    encoded_r = point_compress(point_mul(r, BASE))
    challenge = int.from_bytes(hashlib.sha512(encoded_r+public+message).digest(), 'little') % Q
    signature = encoded_r+((r+challenge*a) % Q).to_bytes(32, 'little')
    return public, signature


def require(condition, label):
    # Never interpolate operands, scalar, key, signature or captured diagnostics.
    if not condition:
        raise AssertionError(label)


def trunc_div(n, d):
    return (abs(n)//d) * (-1 if n < 0 else 1)


def coefficients(values):
    a = values[:10]+[0]
    for i in range(10):
        radix = 2**(26 if i % 2 == 0 else 25)
        carry = trunc_div(a[i], radix)
        a[i] -= carry*radix
        a[i+1] += carry
    a[0] += 19*a[10]
    carry = trunc_div(a[0], 2**26)
    a[0] -= carry*2**26
    a[1] += carry
    return a[:10]


def field(values):
    return sum(x*w for x, w in zip(values, WEIGHTS)) % P


def negative_control(driver):
    # Only deterministic public operands reach the deliberately unpatched TU.
    # A crash without the expected UBSan diagnostic is NOT a successful control.
    cases = ['eq -1 -1', 'reduce '+' '.join(['-1']*19),
             'coeff '+' '.join([str(-(2**27))]+['0']*9)]
    for request in cases:
        result = subprocess.run([driver], input=request+'\n', text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        require(result.returncode != 0 and
                'runtime error: left shift of negative value' in result.stderr,
                'unpatched ECC must fail strict UBSan in '+request.split()[0])
    print('Old-source negative controls: 3 expected signed-negative-shift UBSan failures '
          'observed (equality, degree reduction, coefficient carry); no operands output')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('driver')
    parser.add_argument('--negative-control', action='store_true')
    args = parser.parse_args()
    if args.negative_control:
        negative_control(args.driver)
        return
    requests, expected = [], []
    def case(op, values, result):
        requests.append(op+' '+(' '.join(map(str, values))))
        expected.append(str(result))

    # Equality must cover both the sign-bit fold (INT_MIN) and lower bits, not
    # merely the small, non-negative field limbs observed in a happy-path key.
    special = [-(2**31), -(2**31)+1, -1, 0, 1, 2**31-2, 2**31-1]
    for a in special:
        for b in special:
            case('eq', [a, b], -int(a == b))
    rng = random.Random(0x77488032)  # Public, reproducible corpus, not entropy.
    for bit in range(32):
        for a in [0, -1, -(2**31), 2**31-1]:
            bits = (a & 0xffffffff) ^ (1 << bit)
            b = bits if bits < 2**31 else bits-2**32
            case('eq', [a, b], 0)
    for _ in range(1024):
        a, b = [rng.randrange(-(2**31), 2**31) for _ in range(2)]
        case('eq', [a, a], -1)
        case('eq', [a, b], -int(a == b))

    degree_bound = 14*2**54-1
    for _ in range(256):
        a = [rng.choice([-degree_bound, -1, 0, 1, degree_bound]) for _ in range(19)]
        folded = [a[i]+19*a[i+10] if i < 9 else a[i] for i in range(10)]
        case('reduce', a, ' '.join(map(str, coefficients(folded))))
    coeff_bound = 280*2**54-1
    for sign in [-1, 1]:
        for i in range(10):
            a = [0]*10
            a[i] = sign*coeff_bound
            case('coeff', a, ' '.join(map(str, coefficients(a))))
        a = [sign*coeff_bound]*10
        case('coeff', a, ' '.join(map(str, coefficients(a))))

    # Canonical encodings on both sides of p and through borrow chains.
    p_limbs = [2**(26 if i % 2 == 0 else 25)-1 for i in range(10)]
    p_limbs[0] -= 18
    fields = [[0]*10, [-(2**26)+1]*10, [2**26-1]*10]
    for delta in [-1, 0, 1, 18]:
        a = p_limbs[:]
        a[0] += delta
        fields.append(a)
    for _ in range(256):
        fields.append([rng.randrange(-(2**26)+1, 2**26) for _ in range(10)])
    for a in fields:
        case('contract', a, field(a).to_bytes(32, 'little').hex())
        case('square', a, (field(a)**2 % P).to_bytes(32, 'little').hex())
        b = fields[rng.randrange(len(fields))]
        case('mul', a+b, (field(a)*field(b) % P).to_bytes(32, 'little').hex())
    # fmonty can sum/subtract reduced limbs before multiplying, so fproduct
    # and fsquare_inner must also work up to (but excluding) 2^27 per limb.
    bound = 2**27-1
    wide = [[bound]*10, [-bound]*10]
    wide += [[rng.choice([-bound, -1, 0, 1, bound]) for _ in range(10)] for _ in range(256)]
    for a in wide:
        b = wide[rng.randrange(len(wide))]
        case('square', a, (field(a)**2 % P).to_bytes(32, 'little').hex())
        case('mul', a+b, (field(a)*field(b) % P).to_bytes(32, 'little').hex())

    # RFC 7748 sections 5.2 and 6.1. Constants below are PUBLIC test material.
    vectors = [
        ('a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4',
         'e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c',
         'c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552'),
        ('4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d42ca4169e7918ba0d',
         'e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3efc4cd549c715a493',
         '95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957'),
        ('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a',
         '09'+'00'*31,
         '8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a'),
        ('5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb',
         '09'+'00'*31,
         'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f'),
        ('77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a',
         'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f',
         '4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742')]
    for scalar, point, result in vectors:
        require(x25519(bytes.fromhex(scalar), bytes.fromhex(point)).hex() == result, 'RFC7748 oracle')
        case('x', [scalar, point], result)
    for point in [0, 1, 9, P-1, P, P+1, 2**255-1, 2**256-1]:
        scalar = bytes(rng.randrange(256) for _ in range(32))
        u = point.to_bytes(32, 'little')
        case('x', [scalar.hex(), u.hex()], x25519(scalar, u).hex())
    for _ in range(128):
        scalar, u = [bytes(rng.randrange(256) for _ in range(32)) for _ in range(2)]
        case('x', [scalar.hex(), u.hex()], x25519(scalar, u).hex())
    # Iteration inputs are all checked against the bigint ladder, not only the
    # final RFC checkpoint. One thousand rounds exercises negative carries.
    k = u = bytes.fromhex('09'+'00'*31)
    for i in range(1000):
        result = x25519(k, u)
        case('x', [k.hex(), u.hex()], result.hex())
        k, u = result, k
        if i in [0, 999]:
            require(k.hex() == ['422c8e7a6227d7bca1350b3e2bb7279f7897b87bb6854b783c60e80311ae3079',
                                '684cf59ba83309552800ef566f2f4d3c1c3887c49360e3875f2eb94d99532c51'][i == 999],
                    'RFC7748 iteration oracle')

    # RFC 8032 section 7.1: independent Edwards oracle is first checked against
    # all three short signature vectors; native signs ZeroTier's fixed 32-byte
    # SHA512 prefix and is compared with this oracle's standard Ed25519 result.
    ed_vectors = [
        ('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60', '',
         'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a',
         'e5564300c360ac729086e2cc806e828a'
         '84877f1eb8e5d974d873e06522490155'
         '5fb8821590a33bacc61e39701cf9b46b'
         'd25bf5f0595bbe24655141438e7a100b'),
        ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb', '72',
         '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c',
         '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00'),
        ('c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7', 'af82',
         'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025',
         '6291d657deec24024827e69c3abe01a3'
         '0ce548a284743a445e3680d7db5ac3ac'
         '18ff9b538d16f290ae67f760984dc659'
         '4a7c15e9716ed28dc027beceea1ec40a')]
    seeds = []
    for seed, message, pub, sig in ed_vectors:
        public, signature = ed25519(bytes.fromhex(seed), bytes.fromhex(message))
        require(public.hex() == pub and signature.hex() == sig, 'RFC8032 oracle')
        seeds.append(bytes.fromhex(seed))
    seeds += [bytes(rng.randrange(256) for _ in range(32)) for _ in range(64)]
    for seed in seeds:
        message = bytes(rng.randrange(256) for _ in range(32))
        digest = hashlib.sha512(message).digest()[:32]
        pub, sig = ed25519(seed, digest)
        requests.append('ed '+seed.hex()+' '+message.hex())
        expected.extend([pub.hex(), (sig+digest).hex()])

    result = subprocess.run([args.driver], input='\n'.join(requests)+'\n', text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Suppress runtime operands on failure: even though this corpus is public,
    # logs should never establish a habit of dumping scalar-bearing diagnostics.
    if result.returncode:
        errors = re.sub(r'runtime error:.*', 'runtime error: [operands redacted]', result.stderr)
        print(errors, end='')
        raise AssertionError('sanitized native ECC driver failed')
    require(not result.stderr, 'native ECC unexpected diagnostics')
    actual = result.stdout.splitlines()
    require(len(actual) == len(expected), 'native ECC response count')
    for i, (a, e) in enumerate(zip(actual, expected)):
        require(a == e, 'native ECC/bigint comparison index '+str(i))
    print('ECC public corpus: '+str(len(requests))+' operations / '+str(len(expected))+
          ' comparisons passed; RFC7748 (including 1000 iterations), RFC8032 oracle, '
          'X25519/Ed25519 bigint differential, signed carry/equality/canonical boundaries; no operands output')


if __name__ == '__main__':
    main()
