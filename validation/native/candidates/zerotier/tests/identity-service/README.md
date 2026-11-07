# Mac 离线真实身份 → Android 设备存储验收

只构建固定身份 shim 与 Identity、ECC、Salsa20、SHA512、Utils 五个真实算法 TU，再通过本目录测试 JNI 调用真实 Java service／wrapper／envelope／core。测试 Android Context 和 AndroidKeyStore provider 来自已有 JVM fixture；AES/GCM 仍由真实 JCE 执行。JNI 库仅导出三个身份函数和两个测试 JNI 方法，不编译 manager、node、join、netif、stream 或 libzt 网络层，也不注册任何产品 native。

需要 Mac 现有 clang/JDK、已缓存的固定公共源码和一份**干净的已接受源码导出**。`NATIVE_ROOT` 指向该导出的 `validation/native`。仍沿用完整 manifest 和官方 prepare/apply/verify；即使只编译身份，也不跳过 manager 等已锁输入的校验。工作区未提交 native 草稿会导致校验失败，应使用干净导出，不重置工作区或放宽锁。

```sh
python3 "$NATIVE_ROOT/tool/zerotier_candidate.py" prepare --work "$FRESH_WORK" --cache "$SOURCE_CACHE"
python3 "$NATIVE_ROOT/tool/zerotier_candidate.py" apply --work "$FRESH_WORK"
python3 "$NATIVE_ROOT/tool/zerotier_candidate.py" verify-candidate --work "$FRESH_WORK"
python3 validation/native/candidates/zerotier/tests/identity-service/run.py \
  --native-root "$NATIVE_ROOT" --work "$FRESH_WORK" --output "$NEW_RESULT_JSON"
```

`FRESH_WORK` 和结果文件必须尚不存在，结果文件还必须位于两个源码输入目录之外。缓存由现有 `zerotier_candidate.py fetch` 的固定公开归档组成；本测试不下载。完整候选只接受 0005／0006／0007，不允许 0008；输入 manifest 和准备工具还必须与当前仓库锁匹配。测试使用当前仓库真实 Java 存储源码，结果列明所有实际参与源码及 JDK JNI 头的 SHA-256。

每次只生成一个全新临时真实身份，断言加密文件中没有规范明文身份、service 和新建 wrapper 重读同一实例、损坏密文和旧实例删除被拒绝、显式移除后记录／KeyStore 全空，且存储取得的 Java 私有数组已清零。退出移除测试 provider 和整个私有临时目录；运行时 stderr 和异常字符串均不输出、不保存，避免诊断意外包含秘密。结果仅布尔、计数与源码哈希；`passed` 和两个清理结果必须为 true。

这是 Mac JNI 与真实身份算法的离线证据，**没有 Android ABI、真实 AndroidKeyStore、产品绑定、节点或网络证据**。此测试不使用 sanitizer，不能替代已有固定候选的 ASan/UBSan/ECC 专项。测试 JNI 也不是未来产品身份工厂的发布实现。
