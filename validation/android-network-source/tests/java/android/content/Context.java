package android.content;
/** Synthetic Context for a desktop JVM. No Android APIs or storage are used. */
public class Context {
    public Context getApplicationContext() { return this; }
    public java.io.File getNoBackupFilesDir() { return new java.io.File("/private/tmp"); }
}
