# 扫描公开配对响应

Android 两个应用共享固定的 ZXing Camera Activity（Embedded 4.3.0，Core 3.5.3），相机仅在用户点扫描后打开，限定 QR，关闭图片保存。iOS Flutter 使用 AVFoundation 的 QR 元数据输出。应用只取最多 2048 个 UTF-8 字节的公开响应，回填审查页；仍须核实绑定、来源和有效期，再明确接受和主动连接。拒绝相机权限或取消扫描后可继续手动导入。

[固定 Android 依赖和来源](sources.json)与[Apache 通知](android/notices/QR-NOTICE.txt)随代码保留。Android 提供器使用[固定版 ScanOptions](https://github.com/journeyapps/zxing-android-embedded/blob/v4.3.0/zxing-android-embedded/src/com/journeyapps/barcodescanner/ScanOptions.java)。相机视野、对焦、权限切换、旋转、读屏与实机二维码识别仍需设备验收。

2026-11-06 已从 Maven Central 独立下载固定 AAR 和 JAR，对照各自公布的 SHA-1 并计算 SHA-256。记录见[依赖来源](sources.json)。相机权限和真机识别仍需分别实测。
