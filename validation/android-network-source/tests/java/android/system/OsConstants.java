package android.system;
public final class OsConstants { public static boolean S_ISDIR(int mode) { return (mode & 0170000)==0040000; } }
