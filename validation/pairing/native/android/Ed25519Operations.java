package org.herdr.pairing;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import org.bouncycastle.math.ec.rfc8032.Ed25519;

/** Native-only, pinned BC lightweight API. Does not install a JCA provider. */
final class Ed25519Operations {
    static final int MAX_MESSAGE_BYTES = 65536;
    private Ed25519Operations() {}
    static byte[] publicBytes(byte[] seed) {
        if (seed == null || seed.length != 32) throw new IllegalArgumentException("seed bounds");
        byte[] result = new byte[32];
        Ed25519.generatePublicKey(seed, 0, result, 0);
        return result;
    }
    static String publicLine(byte[] publicKey) {
        if (publicKey == null || publicKey.length != 32) throw new IllegalArgumentException("public bounds");
        byte[] algorithm = "ssh-ed25519".getBytes(StandardCharsets.US_ASCII);
        byte[] wire = ByteBuffer.allocate(51).putInt(algorithm.length).put(algorithm)
            .putInt(publicKey.length).put(publicKey).array();
        return "ssh-ed25519 " + Base64.getEncoder().encodeToString(wire);
    }
    static byte[] sign(byte[] seed, byte[] message) {
        checkMessage(message);
        if (seed == null || seed.length != 32) throw new IllegalArgumentException("seed bounds");
        byte[] signature = new byte[64];
        Ed25519.sign(seed, 0, message, 0, message.length, signature, 0);
        return signature;
    }
    static void checkMessage(byte[] message) {
        if (message == null || message.length > MAX_MESSAGE_BYTES)
            throw new IllegalArgumentException("message bounds");
    }
}
