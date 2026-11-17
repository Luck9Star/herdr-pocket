"""Pure Swift policy tests using macOS AX labels, not iOS device evidence."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "requires macOS Swift and Foundation")
class NativeControlPolicyTests(unittest.TestCase):
    def test_real_label_samples_and_ambiguity(self):
        source = pathlib.Path(__file__).with_name("tauri_ios_direct_ssh.swift").read_text()
        policy = source[source.index("enum NativeControlPolicy {"):source.index("// END NATIVE FRAME POLICY")]
        program = r'''
import Foundation
typealias F = NativeControlPolicy.Fact
let rows = [
    F(identifier: "", label: "＋ 添加主机", role: "button", value: ""),
    F(identifier: "", label: "添加主机", role: "button", value: ""),
    F(identifier: "", label: "普通 SSH", role: "button", value: ""),
    F(identifier: "", label: "普通 SSH 终端", role: "button", value: ""),
    F(identifier: "", label: "主机地址", role: "textField", value: ""),
    F(identifier: "", label: "端口", role: "numberField", value: "22"),
    F(identifier: "", label: "用户名", role: "textField", value: ""),
    F(identifier: "", label: "探测主机指纹", role: "button", value: ""),
    F(identifier: "", label: "我已通过可信渠道独立核对以上指纹。", role: "checkBox", value: "0"),
    F(identifier: "", label: "密码", role: "secureTextField", value: ""),
    F(identifier: "", label: "连接 / 重新连接", role: "button", value: ""),
    F(identifier: "", label: "取消连接", role: "button", value: ""),
    F(identifier: "", label: "重新核对主机指纹", role: "button", value: ""),
    F(identifier: "", label: "取消连接，保留旧信任", role: "button", value: ""),
    F(identifier: "", label: "打开键盘", role: "button", value: ""),
    F(identifier: "", label: "断开连接", role: "button", value: "")
]
func pick(_ label: String, _ id: String? = nil, _ roles: Set<String> = ["button"]) -> Int? {
    NativeControlPolicy.select(rows, identifier: id, label: label, roles: roles)
}
precondition(pick("添加主机") == 1)
precondition(pick("普通 SSH 终端", "add-ssh") == 3)
precondition(pick("未知") == nil)
precondition(pick("不存在", "") == nil)
precondition(pick("端口", "ssh-port", ["numberField"]) == 5)
precondition(pick("密码", "ssh-password", ["secureTextField"]) == 9)
precondition(pick("重新核对主机指纹") == 12)
precondition(pick("取消连接，保留旧信任") == 13)
let duplicate = rows + [F(identifier: "", label: "添加主机", role: "button", value: "")]
precondition(NativeControlPolicy.select(duplicate, identifier: nil, label: "添加主机", roles: ["button"]) == nil)
let idDuplicates = rows + [F(identifier: "target", label: "x", role: "button", value: ""),
                           F(identifier: "target", label: "y", role: "button", value: "")]
precondition(NativeControlPolicy.select(idDuplicates, identifier: "target", label: "添加主机", roles: ["button"]) == nil)
let wrongRole = rows + [F(identifier: "target", label: "other", role: "textField", value: "")]
precondition(NativeControlPolicy.select(wrongRole, identifier: "target", label: "添加主机", roles: ["button"]) == nil)
let mixedDuplicate = wrongRole + [F(identifier: "target", label: "other", role: "button", value: "")]
precondition(NativeControlPolicy.select(mixedDuplicate, identifier: "target", label: "添加主机", roles: ["button"]) == nil)
precondition(NativeControlPolicy.queryChoice(identifierCount: 1, labelCount: 1) == .identifier)
precondition(NativeControlPolicy.queryChoice(identifierCount: 2, labelCount: 1) == .ambiguous)
precondition(NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: 1) == .label)
precondition(NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: 2) == .ambiguous)
precondition(NativeControlPolicy.queryChoice(identifierCount: 0, labelCount: 0) == .none)
precondition(NativeControlPolicy.valueText(NSNumber(value: 0)) == "0")
precondition(NativeControlPolicy.valueText(NSNumber(value: 1)) == "1")
precondition(NativeControlPolicy.valueText(NSNumber(value: 22)) == "22")
precondition(NativeControlPolicy.isPortEditingCandidate(role: 999, stepper: 1, button: 2, value: NSNumber(value: 22)))
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 1, stepper: 1, button: 2, value: "22"))
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 2, stepper: 1, button: 2, value: "22"))
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 999, stepper: 1, button: 2, value: "23"))
precondition(NativeControlPolicy.clearCount(NSNumber(value: 22), placeholder: nil, secure: false) == 2)
precondition(NativeControlPolicy.clearCount("请输入主机地址", placeholder: "请输入主机地址", secure: false) == 0)
precondition(NativeControlPolicy.clearCount("请输入主机地址", placeholder: nil, secure: false) == nil)
precondition(NativeControlPolicy.clearCount("输入密码", placeholder: "输入密码", secure: true) == 0)
precondition(NativeControlPolicy.clearCount("••••", placeholder: nil, secure: true) == nil)
precondition(!NativeControlPolicy.credentialEmpty("••••", placeholder: nil))
precondition(!NativeControlPolicy.credentialEmpty("密码", placeholder: nil))
precondition(NativeControlPolicy.credentialEmpty("密码", placeholder: "密码"))
let unknown = NSObject()
precondition(NativeControlPolicy.valueText(nil) == "")
precondition(NativeControlPolicy.valueText(unknown) == nil)
precondition(!NativeControlPolicy.credentialEmpty(unknown, placeholder: nil))
precondition(NativeControlPolicy.clearCount(unknown, placeholder: nil, secure: true) == nil)
precondition(NativeControlPolicy.clearCount(unknown, placeholder: nil, secure: false) == nil)
precondition(!NativeControlPolicy.isPortEditingCandidate(role: 999, stepper: 1, button: 2, value: unknown))
'''
        with tempfile.TemporaryDirectory(prefix="native-controls-") as temp:
            root = pathlib.Path(temp)
            (root / "Policy.swift").write_text("import Foundation\n" + policy)
            (root / "main.swift").write_text(program)
            build = subprocess.run(["swiftc", "-swift-version", "5", str(root / "Policy.swift"),
                                    str(root / "main.swift"), "-o", str(root / "test")],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(root / "test")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
