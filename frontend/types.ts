export type IconName =
  | "activity" | "alert" | "arrow-down" | "arrow-right" | "bell" | "braces" | "check"
  | "chevron-down" | "chevron-left" | "chevron-right" | "clock" | "code" | "columns"
  | "copy" | "database" | "download" | "external" | "eye" | "filter" | "globe" | "grid"
  | "history" | "layers" | "menu" | "moon" | "more" | "pause" | "play" | "plus" | "refresh"
  | "search" | "server" | "settings" | "shield" | "sparkles" | "square" | "sun" | "table"
  | "terminal" | "trash" | "trend-down" | "trend-up" | "x" | "zap";

export type SourceKey = "mymobile" | "daraz" | "gsmarena" | "mega" | "whatamobile" | "whatmobile";
export type ScrapeMode = "single" | "multiple" | "range" | "full";

export interface ControlJob {
  id: string;
  kind: string;
  label: string;
  status: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  current_step: number;
  total_steps: number;
  return_code?: number | null;
  error?: string | null;
  log_tail?: string;
}
