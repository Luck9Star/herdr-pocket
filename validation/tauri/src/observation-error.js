const errors=Object.freeze({
  host_key_mismatch:'主机公钥不匹配。认证未开始；请通过独立可信渠道核对主机身份。不要直接替换已存公钥；确认变更后再审查新目标并重新配对。',
  authentication_failed:'设备或临时公钥认证失败；请核查主机授权和当前设备身份，再主动连接。未尝试其他凭据。',
  session_mismatch:'socket 与命名会话不一致。请核对会话与 socket 后重新审查。',
  pane_missing:'快照中没有指定 pane 或终端身份已变化。请刷新看板，重新选择目标。',
  resume_target_changed:'原 pane 的终端身份已变化，恢复已停止。请刷新看板并重新选择目标；不会自动切换终端。',
  observe_ended:'主机终端观察通道已结束，画面已陈旧。请核对主机与网络后主动连接。',
  observe_failed:'主机终端观察通道未能建立。请核查会话与 SSH 权限，再主动连接。',
  observe_close_failed:'旧观察通道的结束未确认，连接已取消。请核查主机状态后重新连接。',
  invalid_private_key:'仅支持本轮实验用、未加密的 OpenSSH Ed25519 私钥。',
  invalid_host_key:'主机公钥应为 ssh-ed25519 与完整公钥数据两字段。',
  invalid_config:'资料不完整或格式不支持。核对后重新审查。',
  socket_unavailable:'指定 socket 不可用。请检查会话是否已启动及 SSH 转发权限。',
  timeout:'观察超时，连接已终止。请检查网络与主机，再主动连接。不会自动重试。',
  connection_failed:'SSH 无法连接。请检查地址、端口和网络路径。',
  cancelled:'本次观察已取消。迟到结果不会显示。',
  unsupported_protocol:'服务器快照版本不支持；请核对客户端与主机协议。',
  provider_unavailable:'网络桥接不可用；没有使用系统网络回退。',
  overlay_provider_unavailable:'网络桥接不可用；没有使用系统网络回退。',
  mobile_node_not_started:'请先启动此网络的本机节点；不会回退到系统网络。',
  network_public_mode_unsupported:'公开无秘密模式暂不支持节点启动。',
  network_identity_missing:'本机网络身份尚未配置。',
  network_identity_changed:'网络配置或本机身份已变化；请核对节点后重新连接。',
  mobile_node_binding_mismatch:'网络配置或本机身份已变化；请核对节点后重新连接。',
  overlay_stale_revision:'网络配置或本机身份已变化；请核对节点后重新连接。',
  network_profile_disabled:'网络配置已停用；无法连接。',
  host_selection_changed:'主机资料已变化；请关闭此标签，重新核对主机、设备与路径。',
  pairing_missing:'此主机没有可用的设备配对；请恢复并核对原设备身份。',
  key_unavailable:'本机设备密钥不可用；请解锁设备并恢复原身份，不会自动创建替代身份。',
});
/** Native errors are untrusted: only exact public codes may reach the interface. */
export function observationError(error) {
  return typeof error==='string' && Object.hasOwn(errors,error) ? errors[error]
    : '连接或观察未完成，画面已陈旧。请核对网络、主机与目标后主动连接；不会自动重连或重放。';
}
