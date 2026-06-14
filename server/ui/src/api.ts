import type {
  AppError, AppEvent, AuthStatus, DashboardData, Device, DeviceAccessEntry, DeviceProfile,
  DeviceGame, DeviceTokenStatus, GameDetail, Game, LoginUser, RommResult, SettingsData,
} from './types';
import { updateServerOffset } from './lib/serverTime';

const BASE = '/api/v1/ui';
const ROMM_BASE = '/api/v1/romm';

async function rommReq<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = localStorage.getItem('os_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(ROMM_BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const msg = await r.text().catch(() => String(r.status));
    throw new Error(msg || String(r.status));
  }
  return r.json();
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('os_token');
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method,
    headers: authHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const msg = await r.text().catch(() => String(r.status));
    throw new Error(msg || String(r.status));
  }
  if (r.status === 204) return undefined as T;
  const data = await r.json();
  if (data && typeof (data as any).server_now === 'number') {
    updateServerOffset((data as any).server_now);
  }
  return data as T;
}

const get  = <T>(path: string) => req<T>('GET', path);
const post = <T>(path: string, body?: unknown) => req<T>('POST', path, body ?? {});
const put  = <T>(path: string, body: unknown) => req<T>('PUT', path, body);
const del  = <T>(path: string) => req<T>('DELETE', path);

export const api = {
  authStatus:    () => get<AuthStatus>('/auth/status'),
  loginWithCredentials: (username: string, password: string) =>
    post<{ ok: boolean; admin_token: string }>('/auth/login', { username, password }),
  apiLogout:     () => post<{ ok: boolean }>('/auth/logout'),
  rotate:        () => post<{ admin_token: string }>('/auth/rotate'),
  changeCredentials: (currentPassword: string, newUsername?: string, newPassword?: string) =>
    post<{ ok: boolean }>('/settings/credentials', {
      current_password: currentPassword,
      ...(newUsername ? { new_username: newUsername } : {}),
      ...(newPassword ? { new_password: newPassword } : {}),
    }),

  listUsers:   () => get<{ users: LoginUser[] }>('/users'),
  createUser:  (username: string, password: string) =>
    post<{ ok: boolean }>('/users', { username, password }),
  deleteUser:  (username: string) => del<{ ok: boolean }>(`/users/${encodeURIComponent(username)}`),

  pairDevice:        (deviceId: string, userId?: string) =>
    post<{ token: string }>(`/devices/${deviceId}/token`, userId ? { user_id: userId } : {}),
  revokeDeviceToken: (deviceId: string) => del<void>(`/devices/${deviceId}/token`),
  deviceTokenStatus: (deviceId: string) =>
    get<DeviceTokenStatus>(`/devices/${deviceId}/token`),

  pairByCode:          (code: string) =>
    post<{ device_id: string; display_name: string | null }>('/devices/pair', { code }),
  acceptShare:         (code: string) =>
    post<{ device_id: string; display_name: string | null }>('/devices/accept-share', { code }),
  generateShareCode:   (deviceId: string) =>
    post<{ code: string; expires_in: number }>(`/devices/${deviceId}/share`),
  listDeviceAccess:    (deviceId: string) =>
    get<{ access: DeviceAccessEntry[] }>(`/devices/${deviceId}/access`),
  revokeDeviceAccess:  (deviceId: string, userId: string) =>
    del<void>(`/devices/${deviceId}/access/${encodeURIComponent(userId)}`),

  dashboard:     () => get<DashboardData>('/dashboard'),
  games:         () => get<{ games: Game[] }>('/games'),
  gameDetail:    (id: string) => get<GameDetail>(`/games/${id}`),

  events:        (limit = 100) => get<{ events: AppEvent[] }>(`/events?limit=${limit}`),
  errors:        () => get<{ errors: AppError[] }>('/errors'),
  acknowledge:   (txn: string) => post<{ ok: boolean }>(`/errors/${txn}/acknowledge`),

  devices:       () => get<{ devices: Device[] }>('/devices'),
  deleteDevice:  (id: string) => del<void>(`/devices/${id}`),
  deviceGames:   (id: string) => get<{ games: DeviceGame[] }>(`/devices/${id}/games`),
  restoreAll:    (id: string) => post<{ ok: boolean; queued: number }>(`/devices/${id}/restore-all`, {}),
  setSyncPrefs:  (id: string, prefs: { title_id: string; enabled: boolean }[]) =>
    post<{ ok: boolean }>(`/devices/${id}/games/sync/batch`, { preferences: prefs }),

  setDeviceLabel:   (id: string, name: string) => put<{ ok: boolean }>(`/labels/device/${id}`, { display_name: name }),
  clearDeviceLabel: (id: string) => del<void>(`/labels/device/${id}`),
  setGameLabel:     (id: string, name: string) => put<{ ok: boolean }>(`/labels/game/${id}`, { display_name: name }),
  clearGameLabel:   (id: string) => del<void>(`/labels/game/${id}`),

  pushSnapshot:   (txn: string, targets: { device_id: string; target_profile_uid?: string | null }[]) =>
    post<{ ok: boolean; outbound_ids: string[] }>(`/snapshots/${txn}/push`, { targets }),
  setDeviceDefaultProfile: (deviceId: string, profileUid: string | null) =>
    put<{ ok: boolean }>(`/devices/${deviceId}/default-profile`, { profile_uid: profileUid }),
  retryOutbound:     (txn: string) => post<{ ok: boolean }>(`/outbounds/${txn}/retry`),
  retryAllFailed:    (deviceId: string) => post<{ ok: boolean; retried: number }>(`/devices/${deviceId}/outbounds/retry-failed`),
  deleteSnapshot: (txn: string) => del<{ deleted: string }>(`/snapshots/${txn}`),

  searchRomm: (q: string, limit = 10) =>
    rommReq<{ results: RommResult[] }>('GET', `/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  setRommMapping: (titleId: string, romId: number) =>
    rommReq<{ ok: boolean }>('PUT', `/titles/${titleId}/mapping`, { rom_id: romId }),
  triggerRommScan: () => rommReq<{ ok: boolean }>('POST', '/scan'),

  deviceProfiles: (deviceId: string) =>
    get<{ profiles: DeviceProfile[] }>(`/devices/${deviceId}/profiles`),
  claimProfile: (deviceId: string, profileId: string, userId?: string) =>
    put<{ ok: boolean }>(`/devices/${deviceId}/profiles/${encodeURIComponent(profileId)}`,
      userId ? { user_id: userId } : {}),
  unclaimProfile: (deviceId: string, profileId: string) =>
    del<void>(`/devices/${deviceId}/profiles/${encodeURIComponent(profileId)}`),

  settings:        () => get<SettingsData>('/settings'),
  setRommUser:     (deviceId: string, username: string) =>
    put<{ ok: boolean }>(`/settings/romm_user/${deviceId}`, { username }),
  clearRommUser:   (deviceId: string) => del<{ ok: boolean }>(`/settings/romm_user/${deviceId}`),
  setSwitchUser:   (deviceId: string, username: string) =>
    put<{ ok: boolean }>(`/settings/switch_user/${deviceId}`, { username }),
  clearSwitchUser: (deviceId: string) => del<{ ok: boolean }>(`/settings/switch_user/${deviceId}`),

  rommServerSettings: () =>
    get<{ enabled: boolean; host: string; has_api_key: boolean; source_id: string; romm_username: string | null; romm_connect_status: string; romm_connect_detail: string }>('/settings/romm'),
  setRommServerSettings: (body: { enabled?: boolean; host?: string; api_key?: string; source_id?: string }) =>
    put<{ ok: boolean; romm_username: string | null; romm_connect_status: string; romm_connect_detail: string }>('/settings/romm', body),

  health: () =>
    fetch('/api/health').then(r => r.json() as Promise<{ version: string; service: string }>),
};
