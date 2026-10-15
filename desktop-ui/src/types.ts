export type AnchorAliases = { names?: string[]; profile_urls?: string[]; live_urls?: string[]; platform_user_ids?: string[]; sec_user_ids?: string[]; web_rids?: string[]; room_ids?: string[] };
export type Anchor = { id: string; name: string; profile_url: string; live_url: string; platform_user_id?: string; sec_user_id?: string; web_rid?: string; room_id?: string; output_dir?: string; default_quality?: string; enabled_recording?: boolean; last_live_status?: string; last_resolved_at?: number; last_check_error?: string; aliases?: AnchorAliases };
export type AppState = { anchors: Anchor[]; settings: Record<string, any>; status: Record<string, any>; storage?: Record<string, any>; baidupan: Record<string, any>; update: Record<string, any>; interaction: Record<string, any>; gifts?: Record<string, any>; work_pull: Record<string, any>; recordings: any[]; recording_groups: any[] };
export type DesktopBridge = {
  platform: string;
  getBackgroundSettings(): Promise<Record<string, any>>;
  saveBackgroundSettings(value: Record<string, any>): Promise<Record<string, any>>;
  loginDouyin(): Promise<any>;
  importDouyinCookie(cookie: string): Promise<any>;
  logoutDouyin(): Promise<any>;
  getDouyinStatus(): Promise<any>;
  refreshDouyinSecurity(roomUrl: string): Promise<any>;
  chooseOutputDirectory(): Promise<string>;
  openExternal(url: string): Promise<void>;
  setCompactMode(enabled: boolean): Promise<any>;
  onCompactModeRequested(callback: (enabled: boolean) => void): () => void;
  onDouyinStatusChanged(callback: (status: any) => void): () => void;
};

declare global { interface Window { liveRecorderDesktop?: DesktopBridge } }
