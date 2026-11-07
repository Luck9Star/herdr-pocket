/// Page-local evidence from one explicit connection attempt. No target, terminal
/// contents, credentials or raw errors are retained here.
enum ConnectionStepState { waiting, active, passed, failed, unknown }

class ConnectionDiagnostics {
  ConnectionStepState network=ConnectionStepState.active;
  ConnectionStepState hostKey=ConnectionStepState.waiting;
  ConnectionStepState authentication=ConnectionStepState.waiting;
  ConnectionStepState dashboard=ConnectionStepState.waiting;
  ConnectionStepState firstFrame=ConnectionStepState.waiting;
  bool localNetworkReady=false;
  String? selectedPane,selectedTerminal;
  String guidance='连接进行中 · 结果由实际核验逐步更新';

  void localRouteReady() { localNetworkReady=true; }
  void progress(String phase) {
    switch (phase) {
      case 'connecting':
        // Socket connection and key verification have not been reported yet.
        network=ConnectionStepState.active;
      case 'snapshot':
        // This event follows authenticated and a matched Ed25519 host key.
        network=hostKey=authentication=ConnectionStepState.passed;
        dashboard=ConnectionStepState.active;
      case 'snapshot_received':
        dashboard=ConnectionStepState.passed;
        firstFrame=ConnectionStepState.waiting;
        guidance='会话看板已核验 · 请选择原目标并等待完整画面';
      case 'observing':
        if (dashboard == ConnectionStepState.passed) firstFrame=ConnectionStepState.active;
        guidance='等待所选目标的首张完整画面';
      default:
        break;
    }
  }
  void targetSelected(String pane,String terminal) {
    if (pane.isNotEmpty && terminal.isNotEmpty) { selectedPane=pane; selectedTerminal=terminal; }
  }
  void frameAccepted() {
    if (dashboard != ConnectionStepState.passed || selectedPane == null || selectedTerminal == null) return;
    firstFrame=ConnectionStepState.passed;
    guidance='首张完整画面已接收 · 保持默认观察；输入需另行选择';
  }
  void stopped() {
    _retireActive();
    guidance='连接已停止 · 请重新审查后主动连接，不会自动重试';
  }
  void fail(String code,{bool hostChecked=false,bool hostMatched=false,bool authStarted=false}) {
    if (hostChecked) {
      network=ConnectionStepState.passed;
      if (hostMatched) { hostKey=ConnectionStepState.passed; }
      else { hostKey=ConnectionStepState.failed; }
    }
    if (code == 'host_key_mismatch' && hostChecked && !hostMatched) {
      guidance='主机指纹不符 · 停止认证，通过可信渠道独立核验原主机公钥';
    } else if ((code == 'authentication_failed' || code == 'authentication_aborted') && hostChecked && hostMatched && authStarted) {
      authentication=ConnectionStepState.failed;
      guidance='SSH 认证未通过 · 核验账号及主机上的设备公钥授权';
    } else if (code == 'device_key_unavailable' || code == 'device_key_changed') {
      guidance='设备身份不可用或已变化 · 核验原设备身份，不会生成替代身份';
    } else if ({'network_binding_changed','network_node_not_started','network_identity_unavailable','network_runtime_unavailable','provider_unavailable'}.contains(code)) {
      guidance='本机网络路径未确认 · 前往网络管理核对配置与绑定';
    } else if ({'session_mismatch','pane_missing','invalid_terminal_id','invalid_snapshot','snapshot_rejected','stale_selection','resume_target_changed'}.contains(code)) {
      if (dashboard == ConnectionStepState.active && {'session_mismatch','invalid_snapshot','snapshot_rejected'}.contains(code)) dashboard=ConnectionStepState.failed;
      if (firstFrame == ConnectionStepState.active && {'pane_missing','invalid_terminal_id','stale_selection','resume_target_changed'}.contains(code)) firstFrame=ConnectionStepState.failed;
      guidance='会话或目标未通过核验 · 检查命名会话并重新选择原 pane 和 terminal';
    } else if (code == 'timeout') {
      guidance='连接或读取超时 · 未确认的阶段请重新检查后主动连接';
    } else {
      guidance='连接或观察未完成 · 核对资料后主动重试，未知结果不会自动重放';
    }
    if (authStarted && authentication == ConnectionStepState.waiting) authentication=ConnectionStepState.active;
    _retireActive();
  }
  void _retireActive() {
    if (network == ConnectionStepState.active) network=ConnectionStepState.unknown;
    if (hostKey == ConnectionStepState.active) hostKey=ConnectionStepState.unknown;
    if (authentication == ConnectionStepState.active) authentication=ConnectionStepState.unknown;
    if (dashboard == ConnectionStepState.active) dashboard=ConnectionStepState.unknown;
    if (firstFrame == ConnectionStepState.active) firstFrame=ConnectionStepState.unknown;
  }
  static String label(ConnectionStepState value) => switch (value) {
    ConnectionStepState.waiting => '尚未确认',
    ConnectionStepState.active => '进行中',
    ConnectionStepState.passed => '已核验',
    ConnectionStepState.failed => '未通过',
    ConnectionStepState.unknown => '结果未知',
  };
}
