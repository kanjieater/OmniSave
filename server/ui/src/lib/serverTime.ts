let _offset = 0

export function serverNow(): number {
  return Date.now() + _offset
}

export function updateServerOffset(serverNowMs: number): void {
  _offset = serverNowMs - Date.now()
}
