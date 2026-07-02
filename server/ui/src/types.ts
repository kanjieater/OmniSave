export interface AuthStatus {
  bootstrapped: boolean;
  authenticated: boolean;
  username: string;
  is_admin: boolean;
}

export interface LoginUser {
  username: string;
  is_admin: boolean;
  created_at: string;
}

export interface DeviceTokenStatus {
  has_token: boolean;
  user_id: string | null;
  last_seen: string | null;
}

export interface DashboardStats {
  total_games: number;
  total_devices: number;
  active_errors: number;
  pending_titles: number;
}

export interface RecentGame {
  title_id: string;
  display_name: string | null;
  icon_url: string | null;
  last_activity: string | null;
  head_sequence: number | null;
  status: GameStatus;
  snapshot_count: number;
}

export interface DeviceSummary {
  device_id: string;
  display_name: string | null;
  last_seen: string;
  pending_count: number;
  delivery_failed_count: number;
  is_deleted?: boolean;
}

export interface RecentEvent {
  id: number;
  event_type: string;
  summary: string;
  title_id: string;
  icon_url: string | null;
  device_id: string;
  created_at: string;
}

export interface DashboardData {
  stats: DashboardStats;
  recent_games: RecentGame[];
  devices: DeviceSummary[];
  recent_events: RecentEvent[];
}

export type GameStatus = 'SYNCED' | 'ERROR' | 'CONFLICT' | 'NO_DATA';
export type SyncState = 'SYNCED' | 'OUT_OF_SYNC' | 'UPLOADING' | 'DOWNLOADING' | 'NO_DELIVERY' | 'DELIVERY_FAILED';

export interface Game {
  title_id: string;
  display_name: string | null;
  icon_url: string | null;
  snapshot_count: number;
  device_count: number;
  last_activity: string | null;
  status: GameStatus;
}

export interface Snapshot {
  transaction_id: string;
  sequence_num: number | null;
  device_id: string;
  device_name: string | null;
  ingest_timestamp: string;
  sha256: string;
  parent_sequence: number | null;
  state: string;
  is_head: boolean;
  archive_size_bytes: number | null;
  owner_user_id: string | null;
}

export interface DeviceSyncEntry {
  device_id: string;
  device_name: string | null;
  last_seen: string | null;
  sync_state: SyncState;
  local_sequence: number | null;
  cloud_head_sequence: number | null;
  // view model fields — display only
  sync_enabled: boolean;
  pending_delivery: boolean;
  last_synced_at: string | null;
  hardware_type: string | null;
  client_type: string | null;
  failed_transaction_id: string | null;
}

export interface GameDetail {
  title_id: string;
  display_name: string | null;
  icon_url: string | null;
  rom_id: number | null;
  status: GameStatus;
  head_sequence: number | null;
  snapshots: Snapshot[];
  device_sync_matrix: DeviceSyncEntry[];
}

export interface AppEvent {
  id: number;
  event_type: string;
  summary: string;
  title_id: string;
  icon_url: string | null;
  device_id: string;
  created_at: string;
}

export interface AppError {
  transaction_id: string;
  direction: 'inbound' | 'outbound';
  title_id: string;
  device_id: string;
  game_name?: string | null;
  icon_url?: string | null;
  device_name?: string | null;
  hardware_type?: string | null;
  client_type?: string | null;
  state: string;
  created_at: string;
  acknowledged: boolean;
}

export interface Device {
  device_id: string;
  display_name: string | null;
  last_seen: string;
  hardware_type: string | null;
  client_type: string | null;
  owner_user_id: string | null;
  pending_count: number;
  delivery_failed_count: number;
  is_deleted?: boolean;
  default_profile_uid?: string | null;
  default_profile_name?: string | null;
}

export interface DeviceAccessEntry {
  user_id: string;
  granted_by: string;
  created_at: string;
}

export interface DeviceGame {
  title_id: string;
  display_name: string | null;
  icon_url: string | null;
  sync_enabled: boolean;
  sync_state: SyncState;
  pending_delivery: boolean;
  last_synced_at: string | null;
}

export interface SettingsData {
  romm_users: Record<string, string>;
  switch_users: Record<string, string>;
}

export interface RommResult {
  id: number;
  name: string;
  icon_url: string | null;
}

export interface DeviceProfile {
  profile_id: string;
  profile_name: string;
  display_hint: string;
  user_id: string | null;
  is_mine: boolean;
}

export interface PlaytimeGame {
  title_id: string;
  display_name: string;
  total_sec: number;
  minutes: number;
  icon_url?: string | null;
}

export interface PlaytimeDay {
  date: string;    // "YYYY-MM-DD"
  minutes: number;
  games: PlaytimeGame[];
}
