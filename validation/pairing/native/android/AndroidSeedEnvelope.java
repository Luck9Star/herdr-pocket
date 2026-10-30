package org.herdr.pairing;

import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Compile-only bridge, API 35 baseline. No key is created by class loading.
 * Wraps a locally generated Ed25519 seed; NOT a hardware Ed25519 signer.
 * Caller must persist only the envelope in app noBackupFilesDir, and keep all
 * seed/signing calls within native code, never JS/Dart or exported config.
 */
public final class AndroidSeedEnvelope {
    private static final String PREFIX = "org.herdr.pocket.device-key.v1.";
    private final KeyStore keyStore;
    public AndroidSeedEnvelope() throws Exception {
        if (Build.VERSION.SDK_INT < 35) throw new UnsupportedOperationException("API 35 storage prototype baseline");
        keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
    }
    private String alias(String handle) {
        if (!handle.matches("[a-f0-9]{32}")) throw new IllegalArgumentException("local handle");
        return PREFIX + handle;
    }
    private SecretKey existing(String handle) throws Exception {
        // Never generate on read: lost/invalidated key requires explicit new pairing.
        SecretKey key = (SecretKey) keyStore.getKey(alias(handle), null);
        if (key == null) throw new IllegalStateException("protected key missing");
        return key;
    }
    public byte[] createEnvelope(String handle, byte[] localSeed) throws Exception {
        if (localSeed.length != 32) throw new IllegalArgumentException("Ed25519 seed length");
        String name = alias(handle);
        if (keyStore.containsAlias(name)) throw new IllegalStateException("handle already exists");
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(name,
            KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).setUnlockedDeviceRequired(true).build());
        generator.generateKey();
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, existing(handle));
            cipher.updateAAD(alias(handle).getBytes(StandardCharsets.UTF_8));
            byte[] encrypted = cipher.doFinal(localSeed);
            byte[] iv = cipher.getIV();
            if (iv.length != 12 || encrypted.length != 48) throw new IllegalStateException("envelope bounds");
            byte[] envelope = new byte[61];
            envelope[0] = 1;
            System.arraycopy(iv, 0, envelope, 1, 12);
            System.arraycopy(encrypted, 0, envelope, 13, 48);
            return envelope;
        } catch (Exception failure) {
            keyStore.deleteEntry(name);
            throw failure;
        }
    }
    // Internal native callback: caller signs with its pinned Ed25519 library and
    // must not retain/return seed. This method must not be a GUI bridge method.
    public interface SeedOperation<T> { T run(byte[] seed) throws Exception; }
    public <T> T withSeed(String handle, byte[] envelope, SeedOperation<T> operation) throws Exception {
        if (envelope.length != 61 || envelope[0] != 1) throw new IllegalArgumentException("envelope format");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, existing(handle), new GCMParameterSpec(128, envelope, 1, 12));
        cipher.updateAAD(alias(handle).getBytes(StandardCharsets.UTF_8));
        byte[] seed = cipher.doFinal(envelope, 13, 48);
        try { return operation.run(seed); }
        finally { Arrays.fill(seed, (byte) 0); }
    }
    public void delete(String handle) throws Exception { keyStore.deleteEntry(alias(handle)); }
}
