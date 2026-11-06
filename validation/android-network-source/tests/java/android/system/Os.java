package android.system;
public final class Os {
    public static int badIndex=-1, badMode=0040700, badUid=100;
    public static StructStat lstat(String path) {
        int index=path.equals("/private/tmp") ? 0 : path.endsWith("herdr-tailscale-state-v1") ? 1 : path.endsWith("/runtime") ? 2 : 3;
        StructStat s=new StructStat(); s.st_mode=index==0 ? 0040771 : 0040700; s.st_uid=100;
        if(index==badIndex) { s.st_mode=badMode; s.st_uid=badUid; }
        return s;
    }
}
