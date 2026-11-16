"""Compile the consent fixture against the real Android API, never host boot APIs."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

RECEIVER=Path(__file__).parent/'tauri-dual-auth-receiver'
def command(*args):
    return subprocess.run(list(map(str,args)),capture_output=True,text=True)
def dex_methods(data):
    def table(at):return struct.unpack_from('<II',data,at)
    size,offset=table(56);strings=[]
    for i in range(size):
        at=struct.unpack_from('<I',data,offset+4*i)[0]
        while data[at]&128:at+=1
        at+=1;strings.append(data[at:data.index(b'\0',at)].decode('utf8'))
    size,offset=table(64);types=[strings[struct.unpack_from('<I',data,offset+4*i)[0]] for i in range(size)]
    size,offset=table(88)
    return {(types[owner],strings[name]) for owner,_,name in (struct.unpack_from('<HHI',data,offset+8*i) for i in range(size))}

class ReceiverBuildGuardTests(unittest.TestCase):
    def test_compiler_uses_android_boot_api_and_all_listener_classes(self):
        script=(RECEIVER/'build.sh').read_text()
        self.assertIn('-source 8 -target 8 -Xlint:-options -bootclasspath "$jar"',script)
        self.assertIn('"$tmp/classes/dev/herdrpocket/dualtestauth/"*.class',script)
        self.assertNotIn('-classpath "$jar"',script)

class ReceiverApi35Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sdk=os.environ.get('ANDROID_HOME')
        if not sdk:raise unittest.SkipTest('ANDROID_HOME required for real Android35 API checks')
        cls.jar=Path(sdk)/'platforms/android-35/android.jar'
        if not cls.jar.is_file():raise unittest.SkipTest('Android35 platform jar unavailable')
        cls.temporary=tempfile.TemporaryDirectory(prefix='herdr-auth-api35-');cls.root=Path(cls.temporary.name)
        cls.classes=cls.root/'classes';cls.classes.mkdir()
        result=cls.compile(RECEIVER/'AuthActivity.java')
        if result.returncode:raise AssertionError(result.stderr)
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()
    @classmethod
    def compile(cls,*sources):
        return command('javac','-source','8','-target','8','-Xlint:-options','-bootclasspath',cls.jar,'-classpath',cls.classes,'-d',cls.classes,*sources)
    def test_unsupported_host_jdk_io_is_rejected(self):
        source=self.root/'Unsupported.java'
        source.write_text('class Unsupported { void call(java.nio.file.Path p) throws Exception { java.nio.file.Files.readString(p); java.nio.file.Files.writeString(p,"x"); } }')
        result=self.compile(source)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('readString',result.stderr);self.assertIn('writeString',result.stderr)
    def test_bounded_private_io_executes_exact_production_helpers(self):
        source=self.root/'IoProbe.java'
        source.write_text('''package dev.herdrpocket.dualtestauth;
import java.io.*;
public class IoProbe {
 static void put(File root, byte[] data) throws Exception {try(FileOutputStream out=new FileOutputStream(new File(root,"port"))){out.write(data);}}
 public static void main(String[] args) throws Exception {
  File root=new File(args[0]);root.mkdir();
  for(String value:new String[]{"1","43123","65535"}) {put(root,value.getBytes("US-ASCII"));if(!value.equals(AuthActivity.readExpectedPort(root)))throw new Error();}
  for(String value:new String[]{"","0","01","65536","99999","43123\\n","123456","bad"}) {put(root,value.getBytes("US-ASCII"));try {AuthActivity.readExpectedPort(root);throw new Error();} catch(IOException expected) {}}
  put(root,new byte[100000]);try {AuthActivity.readExpectedPort(root);throw new Error();} catch(IOException expected) {}
  for(int length:new int[]{1,4096}) {AuthActivity.writeApprovedUrl(root,new byte[length]);if(new File(root,"approved-url").length()!=length)throw new Error();}
  for(int length:new int[]{0,4097}) {try {AuthActivity.writeApprovedUrl(root,new byte[length]);throw new Error();} catch(IOException expected) {}}
 }
}''')
        result=self.compile(source);self.assertEqual(result.returncode,0,result.stderr)
        result=command('java','-cp',str(self.classes)+os.pathsep+str(self.jar),'dev.herdrpocket.dualtestauth.IoProbe',self.root/'files')
        self.assertEqual(result.returncode,0,result.stderr)
    def test_real_dex_references_supported_stream_apis_and_listener(self):
        dex=self.root/'dex';dex.mkdir(exist_ok=True)
        d8=Path(os.environ['ANDROID_HOME'])/'build-tools/35.0.0/lib/d8.jar'
        classes=sorted((self.classes/'dev/herdrpocket/dualtestauth').glob('AuthActivity*.class'))
        result=command('java','-cp',d8,'com.android.tools.r8.D8','--lib',self.jar,'--min-api','35','--output',dex,*classes)
        self.assertEqual(result.returncode,0,result.stderr)
        methods=dex_methods((dex/'classes.dex').read_bytes())
        self.assertIn(('Ljava/io/FileInputStream;','read'),methods)
        self.assertIn(('Ljava/io/FileOutputStream;','write'),methods)
        self.assertTrue(any(owner.endswith('AuthActivity$1;') and name=='onClick' for owner,name in methods))
        self.assertFalse(any(owner=='Ljava/nio/file/Files;' and name in {'readString','writeString'} for owner,name in methods))
        self.assertFalse(any(owner=='Ljava/lang/invoke/LambdaMetafactory;' for owner,name in methods))

if __name__=='__main__':unittest.main()
