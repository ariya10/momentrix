export interface Asset { id: string; filename: string; duration: number; width: number; height: number }
export interface Run { id: string; project_id: string; stage: string; status: string; created_at: string; updated_at?: string; started_at?: string; finished_at?: string; execution_id?: string | null; error?: string | null; warnings: string[]; completed_stages?: string[]; candidate_count?: number; rendered_count?: number; correlation_id?: string; processing_preset?: string | null }
export interface Project { id: string; name: string; content_type: string; created_at: string; legacy: boolean; assets: Asset[]; runs: Run[] }
export interface Metrics { total_projects: number; completed_projects: number; processing_jobs: number; failed_jobs: number; total_clips: number; approved_clips: number; rejected_clips: number; exported_clips: number; source_seconds: number; average_processing_seconds: number | null; score_distribution: {score: string | number; count: number}[]; rejected_categories: Record<string,number>; stage_seconds: Record<string,number> }
export interface Health { n8n_configured: boolean; ffmpeg: boolean; ffprobe: boolean; whisper_model_available: boolean; whisper_model: string; ollama_model_available: boolean; ollama_model: string; free_disk_bytes: number; cpu_threads?: number; max_input_bytes?: number }
export interface Campaign { id: string; name: string; category: string; creator: string; language: string | null; min_duration: number; max_duration: number; preferred_min: number; preferred_max: number; count: number; required_keywords: string[]; required_hashtags: string[]; hook_requires: string[]; caption_requires: string[]; prohibited_content: string[]; manual_review: string[]; layout: string; authorization_required: boolean; archived: boolean; platform?: string; date_start?: string | null; date_end?: string | null }
export interface Region { x: number; y: number; width: number; height: number }
export interface Span { start: number; end: number }
export interface PublishingMetadata {
  title: string
  hook: string
  caption: string
  description: string
  hashtags: string[]
  instagram_caption: string
  tiktok_caption: string
  thumbnail_text: string
}
export interface Caption extends Span { text: string }
export interface Edit {
  subtitle_outline?: number; safe_margin?: number; max_lines?: number; subtitle_background?: boolean; hook_position?: string
  start_seconds: number; end_seconds: number; cuts: Span[]; layout: string; track_id?: number | null; roi?: Region | null; facecam?: Region | null; gameplay?: Region | null;
  subtitle_style: string; subtitle_position: string; subtitle_font: string; subtitle_size: number; subtitle_color: string; highlight_color: string; captions: Caption[] | null; hook: string; hook_seconds: number; normalize_audio: boolean; denoise: boolean; fade_in: boolean; fps: number; resolution: number
}
export interface Clip {
  description: string; instagram_caption?: string; tiktok_caption?: string; thumbnail_text?: string
  component_scores?: Record<string,number>; evidence?: {start:number; end:number; signal:string; detail:string}[]; source_captions?: Caption[]; hook_options?: string[]
  id: string; clip_id: string; project_name: string; project_id: string; campaign: string; revision: number; exported: boolean; asset_id?: string;
  start_seconds: number; end_seconds: number; duration: number; score: number; title: string; caption: string; hook: string; category: string; hashtags: string[];
  supporting_transcript: string; selection_reason: string; score_breakdown: Record<string,number>; review_flags: string[]; review: {status: string; note: string}; render_layout?: string; edit?: Edit; rendered_preview?: string | null; rendered_layout?: string | null
}
export const terminal = new Set(['completed','completed_with_warnings','awaiting_review','failed','cancelled','exported'])
