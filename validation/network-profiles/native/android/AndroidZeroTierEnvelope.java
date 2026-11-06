package org.herdr.network;

import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.security.Key;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** ZeroTier-only, non-exportable AndroidKeyStore envelope. */
final class AndroidZeroTierEnvelope implements ZeroTierDeviceStoreCore.Backend {
    private final KeyStore store;

    AndroidZeroTierEnvelope() throws Exception {
        if (Build.VERSION.SDK_INT < 35) throw new UnsupportedOperationException("API 35 required");
        store=KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
    }

    private static String checkedAlias(String name) {
        String prefix=ZeroTierDeviceStoreCore.KEYSTORE_ALIAS_PREFIX;
        if (name==null || !name.startsWith(prefix)
            || !name.equals(ZeroTierDeviceStoreCore.alias(name.substring(prefix.length()))))
            throw new IllegalArgumentException("invalid device alias");
        return name;
    }

    private SecretKey existing(String name) throws Exception {
        Key key=store.getKey(checkedAlias(name),null);
        if (!(key instanceof SecretKey)) throw new IllegalStateException("device key unavailable");
        return (SecretKey)key;
    }

    @Override public byte[] create(String alias,byte[] aad,byte[] plaintext) throws Exception {
        String name=checkedAlias(alias);
        if (store.containsAlias(name)) throw new IllegalStateException("device key already exists");
        boolean attempted=false;
        try {
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(name,KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true).setUnlockedDeviceRequired(true).build());
            attempted=true;
            generator.generateKey();
            Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE,existing(name)); cipher.updateAAD(aad);
            byte[] ciphertext=cipher.doFinal(plaintext), iv=cipher.getIV();
            if (iv==null || iv.length!=12 || ciphertext.length!=plaintext.length+16)
                throw new IllegalStateException("invalid device envelope");
            byte[] envelope=Arrays.copyOf(iv,iv.length+ciphertext.length);
            System.arraycopy(ciphertext,0,envelope,iv.length,ciphertext.length);
            return envelope;
        } catch (Exception failure) {
            if (attempted) try { store.deleteEntry(name); } catch (Exception cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    @Override public void open(String alias,byte[] aad,byte[] envelope,ZeroTierDeviceStoreCore.PlainOperation operation) throws Exception {
        if (envelope==null || envelope.length<28 || operation==null) throw new IllegalArgumentException("invalid device envelope");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,existing(alias),new GCMParameterSpec(128,envelope,0,12));
        cipher.updateAAD(aad);
        byte[] plaintext=cipher.doFinal(envelope,12,envelope.length-12);
        try { operation.run(plaintext); } finally { Arrays.fill(plaintext,(byte)0); }
    }

    @Override public void delete(String alias) throws Exception { store.deleteEntry(checkedAlias(alias)); }
}
