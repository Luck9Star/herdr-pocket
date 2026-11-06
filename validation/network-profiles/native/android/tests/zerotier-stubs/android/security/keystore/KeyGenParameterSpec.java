package android.security.keystore;
import java.security.spec.AlgorithmParameterSpec;
public final class KeyGenParameterSpec implements AlgorithmParameterSpec {
    public String name; public int purposes,size; public String mode,padding; public boolean randomized,unlocked;
    public static final class Builder {
        private final KeyGenParameterSpec spec=new KeyGenParameterSpec();
        public Builder(String name,int purposes) { spec.name=name; spec.purposes=purposes; }
        public Builder setKeySize(int n) { spec.size=n; return this; }
        public Builder setBlockModes(String mode) { spec.mode=mode; return this; }
        public Builder setEncryptionPaddings(String padding) { spec.padding=padding; return this; }
        public Builder setRandomizedEncryptionRequired(boolean value) { spec.randomized=value; return this; }
        public Builder setUnlockedDeviceRequired(boolean value) { spec.unlocked=value; return this; }
        public KeyGenParameterSpec build() { return spec; }
    }
}
