package android.content;
import android.app.KeyguardManager;
import java.io.File;
public final class Context {
    private final File dir; private final KeyguardManager lock;
    public Context(File dir,KeyguardManager lock) { this.dir=dir; this.lock=lock; }
    public Context getApplicationContext() { return this; }
    public <T> T getSystemService(Class<T> cls) { return cls.cast(lock); }
    public File getNoBackupFilesDir() { return dir; }
}
