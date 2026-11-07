package android.app;
public final class KeyguardManager {
    public boolean locked; public long delayMillis;
    public boolean isDeviceLocked() {
        if(delayMillis>0) try { Thread.sleep(delayMillis); } catch(InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException(error); }
        return locked;
    }
}
