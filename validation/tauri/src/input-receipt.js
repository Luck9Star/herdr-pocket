// Only expose a receipt after the native transport has matched the reply.
export function matchedReceipt(value, target, length) {
  if (!value || typeof value !== 'object' || !target ||
      !/^[0-9a-f]{32}$/.test(value.requestId) ||
      value.paneId !== target.paneId || value.terminalId !== target.terminalId ||
      value.acceptedBytes !== length) return null;
  return {requestId:value.requestId, paneId:value.paneId,
    terminalId:value.terminalId, acceptedBytes:value.acceptedBytes};
}
