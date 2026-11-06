package org.herdr.network;

import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Separate alias namespace from SSH device keys; creates keys only during explicit creation. */
final class AndroidNetworkEnvelope implements NetworkSecretStoreCore.Backend {
    private static final String PREFIX = "org.herdr.pocket.network-secret.v1.";
    private final KeyStore store;
    AndroidNetworkEnvelope() throws Exception {
        if (Build.VERSION.SDK_INT < 35) throw new UnsupportedOperationException("API 35 required");
        store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
    }
    private String alias(String handle) { return PREFIX + NetworkSecretStoreCore.checkedHandle(handle); }
    private SecretKey existing(String handle) throws Exception {
        SecretKey key = (SecretKey) store.getKey(alias(handle), null);
        if (key == null) throw new IllegalStateException("network key missing; explicit recovery required");
        return key;
    }
    @Override public byte[] create(String handle, byte[] aad, byte[] payload) throws Exception {
        String name = alias(handle);
        if (store.containsAlias(name)) throw new IllegalStateException("network key alias already exists");
        boolean attempted = false;
        try {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(name, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true).setUnlockedDeviceRequired(true).build());
            attempted = true;
            generator.generateKey();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, existing(handle));
            cipher.updateAAD(aad);
            byte[] ciphertext = cipher.doFinal(payload), iv = cipher.getIV();
            if (iv.length != 12 || ciphertext.length != payload.length + 16) throw new IllegalStateException("envelope bounds");
            byte[] result = new byte[iv.length + ciphertext.length];
            System.arraycopy(iv, 0, result, 0, iv.length);
            System.arraycopy(ciphertext, 0, result, iv.length, ciphertext.length);
            return result;
        } catch (Exception failure) {
            if (attempted) try { store.deleteEntry(name); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }
    @Override public void open(String handle, byte[] aad, byte[] envelope, NetworkSecretStoreCore.PayloadOperation operation) throws Exception {
        if (envelope.length < 28) throw new IllegalArgumentException("invalid envelope");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, existing(handle), new GCMParameterSpec(128, envelope, 0, 12));
        cipher.updateAAD(aad);
        byte[] plaintext = cipher.doFinal(envelope, 12, envelope.length - 12);
        try { operation.run(plaintext); } finally { Arrays.fill(plaintext, (byte) 0); }
    }
    @Override public void delete(String handle) throws Exception { store.deleteEntry(alias(handle)); }
}
