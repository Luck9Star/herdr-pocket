"""Exact receiver behavior on controlled UI doubles; not an Android touch/layout proof."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_tauri_android_dual_receiver import RECEIVER, command

SOURCES={
    'android/content/Context.java':'package android.content; public class Context { public android.content.res.Resources getResources(){return new android.content.res.Resources();}}',
    'android/content/res/Resources.java':'package android.content.res; public class Resources {public android.util.DisplayMetrics getDisplayMetrics(){return new android.util.DisplayMetrics();}}',
    'android/util/DisplayMetrics.java':'package android.util; public class DisplayMetrics {public float density=2;}',
    'android/os/Bundle.java':'package android.os; public class Bundle {}',
    'android/app/Activity.java':'package android.app; public class Activity extends android.content.Context {public static java.io.File root; public static android.content.Intent intent; public android.view.View content; public void onCreate(android.os.Bundle b){} public void onWindowFocusChanged(boolean b){} public android.content.Intent getIntent(){return intent;} public java.io.File getFilesDir(){return root;} public void setContentView(android.view.View v){content=v;}}',
    'android/content/Intent.java':'package android.content; public class Intent {public static final String ACTION_VIEW="android.intent.action.VIEW"; public String action;public android.net.Uri uri; public Intent(String value){action=ACTION_VIEW;uri=new android.net.Uri(value);} public String getAction(){return action;}public android.net.Uri getData(){return uri;}}',
    'android/net/Uri.java':'package android.net; public class Uri {private java.net.URI uri;public Uri(String value){uri=java.net.URI.create(value);} public String getScheme(){return uri.getScheme();}public String getHost(){return uri.getHost();}public int getPort(){return uri.getPort();}public String getUserInfo(){return uri.getUserInfo();}public String getFragment(){return uri.getFragment();}public String toString(){return uri.toString();}}',
    'android/graphics/Insets.java':'package android.graphics;public class Insets {public int left=10,top=20,right=30,bottom=40;}',
    'android/view/WindowInsets.java':'package android.view;public class WindowInsets {public static class Type {public static int systemBars(){return 1;}public static int displayCutout(){return 2;}public static int systemGestures(){return 4;}}public android.graphics.Insets getInsets(int mask){if(mask!=7)throw new Error();return new android.graphics.Insets();}}',
    'android/view/View.java':'package android.view;public class View {public boolean enabled=true,focusable,touchFocusable,focused;public int[] padding;public CharSequence description;public OnClickListener click;public OnApplyWindowInsetsListener insets;\npublic interface OnClickListener{void onClick(View v);}public interface OnApplyWindowInsetsListener{WindowInsets onApplyWindowInsets(View v,WindowInsets i);}\npublic void setEnabled(boolean value){enabled=value;}public boolean isEnabled(){return enabled;}public void setContentDescription(CharSequence value){description=value;}public void setFocusable(boolean value){focusable=value;}public void setFocusableInTouchMode(boolean value){touchFocusable=value;}public boolean requestFocusFromTouch(){focused=enabled&&focusable&&touchFocusable;return focused;}public void setPadding(int a,int b,int c,int d){padding=new int[]{a,b,c,d};}public void setOnApplyWindowInsetsListener(OnApplyWindowInsetsListener value){insets=value;}public void requestApplyInsets(){insets.onApplyWindowInsets(this,new WindowInsets());}public void setAccessibilityLiveRegion(int value){}public void setMinimumHeight(int value){}public void setOnClickListener(OnClickListener value){click=value;}}',
    'android/widget/TextView.java':'package android.widget;public class TextView extends android.view.View {public CharSequence text;public int gravity;public TextView(android.content.Context c){}public void setText(CharSequence value){text=value;}public void setGravity(int value){gravity=value;}}',
    'android/widget/Button.java':'package android.widget;public class Button extends TextView {public Button(android.content.Context c){super(c);}}',
    'android/widget/LinearLayout.java':'package android.widget;public class LinearLayout extends android.view.View {public static final int VERTICAL=1;public java.util.List<android.view.View> children=new java.util.ArrayList<>();public int gravity;public LinearLayout(android.content.Context c){}public void setOrientation(int value){}public void setGravity(int value){gravity=value;}public void addView(android.view.View v){children.add(v);}}',
}
PROBE='package dev.herdrpocket.dualtestauth;\nimport android.app.Activity;import android.widget.*;import java.io.*;import java.nio.file.Files;\npublic class UiProbe {\n static void check(boolean value){if(!value)throw new Error();}\n static AuthActivity setup(File root,String url)throws Exception {root.mkdir();Activity.root=root;Activity.intent=new android.content.Intent(url);Files.write(new File(root,"port").toPath(),"43123".getBytes("US-ASCII"));AuthActivity a=new AuthActivity();a.onCreate(null);return a;}\n public static void main(String[] args)throws Exception {\n  File root=new File(args[0]);AuthActivity a=setup(root,"https://127.0.0.1:43123/auth/synthetic");LinearLayout layout=(LinearLayout)a.content;\n  TextView origin=(TextView)layout.children.get(0),status=(TextView)layout.children.get(1);Button button=(Button)layout.children.get(2);\n  String expected="隔离测试控制面：127.0.0.1:43123";\n  check(layout.gravity==17&&java.util.Arrays.equals(layout.padding,new int[]{58,68,78,88}));check(origin.text.equals(expected));check(status.description.equals("ready"));check(button.enabled&&button.focused&&button.description.equals("dual_auth_approve"));check(!new File(root,"approved-url").exists());\n  button.focused=false;a.onWindowFocusChanged(true);check(button.focused);\n  button.click.onClick(button);check(!button.enabled&&status.description.equals("delivered")&&origin.text.equals(expected));\n  Files.write(new File(root,"approved-url").toPath(),new byte[]{42});button.click.onClick(button);check(Files.readAllBytes(new File(root,"approved-url").toPath()).length==1);\n  File failed=new File(args[0]+"-failed");AuthActivity b=setup(failed,"https://127.0.0.1:43123/auth/synthetic");new File(failed,"approved-url").mkdir();LinearLayout second=(LinearLayout)b.content;Button failButton=(Button)second.children.get(2);failButton.click.onClick(failButton);check(!failButton.enabled&&((TextView)second.children.get(1)).description.equals("delivery_failed")&&((TextView)second.children.get(0)).text.equals(expected));\n  int n=0;for(String url:new String[]{"https://example.invalid:43123/","https://127.0.0.1:43124/","https://127.0.0.1:43123/#fragment"}){AuthActivity rejected=setup(new File(args[0]+"-bad"+(n++)),url);LinearLayout views=(LinearLayout)rejected.content;check(!((Button)views.children.get(2)).enabled&&((TextView)views.children.get(1)).description.equals("source_mismatch"));}\n }\n}'

class ReceiverUiContractTests(unittest.TestCase):
    def test_insets_focus_explicit_single_click_and_separate_source_status(self):
        sdk=os.environ.get('ANDROID_HOME')
        if not sdk: self.skipTest('ANDROID_HOME required for real Android35 compilation')
        jar=Path(sdk)/'platforms/android-35/android.jar'
        if not jar.is_file():self.skipTest('Android35 platform jar unavailable')
        with tempfile.TemporaryDirectory(prefix='herdr-auth-ui-') as temporary:
            root=Path(temporary);classes=root/'classes';classes.mkdir()
            result=command('javac','-source','8','-target','8','-Xlint:-options','-bootclasspath',jar,'-d',classes,RECEIVER/'AuthActivity.java')
            self.assertEqual(result.returncode,0,result.stderr)
            paths=[]
            for name,source in SOURCES.items():
                path=root/'stubs'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source);paths.append(path)
            stubs=root/'mock-classes';stubs.mkdir()
            result=command('javac','-d',stubs,*paths);self.assertEqual(result.returncode,0,result.stderr)
            probe=root/'UiProbe.java';probe.write_text(PROBE)
            classpath=os.pathsep.join(map(str,[stubs,classes,jar]))
            result=command('javac','-classpath',classpath,'-d',classes,probe);self.assertEqual(result.returncode,0,result.stderr)
            result=command('java','-cp',classpath,'dev.herdrpocket.dualtestauth.UiProbe',root/'private-files')
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
