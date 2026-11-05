// The preview assists human review; native parsing remains the authority.
export function previewPairingResponse(raw) {
  if (typeof raw !== 'string' || new TextEncoder().encode(raw).length > 2048) throw new Error('无效响应');
  const value=JSON.parse(raw);
  if (!value || Array.isArray(value) || typeof value !== 'object' ||
      !['account','host_key','fingerprint','status','request_id'].every(k=>typeof value[k] === 'string') ||
      !Number.isSafeInteger(value.issued_at) || !Number.isSafeInteger(value.expires_at) ||
      typeof value.authorization_added !== 'boolean' || !['authorized','revoked'].includes(value.status)) throw new Error('无效响应字段');
  return [
    '以下内容未经认证，须独立核实来源：',
    `账号：${value.account}`, `主机指纹：${value.host_key}`, `设备指纹：${value.fingerprint}`,
    `状态：${value.status === 'authorized' ? '授权' : '撤销'} (${value.status})`,
    `主机是否新增授权：${value.authorization_added ? '是' : '否'}`,
    `签发 Unix 秒：${value.issued_at}`, `到期 Unix 秒：${value.expires_at}`,
    `请求 ID：${value.request_id}`,
    '最终匹配、版本、字段和有效期由原生层严格校验。'
  ].join('\n');
}
