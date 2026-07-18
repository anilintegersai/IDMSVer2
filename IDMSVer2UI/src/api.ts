import axios from "axios";

const API_BASE = "/api/v1";

export interface TocItem {
  sl_no: string;
  section_number: string;
  item_text: string;
  page_no: string;
  page_ref: string;
  bookmark: string;
  level: number;
  children: TocItem[];
}

export interface DocumentListItem {
  name: string;
  path: string;
}

export interface MergeResult {
  output_path: string;
  logical_id: string | null;
  embedded_objects_count: number;
}

export interface ApiResponse<T> {
  success: boolean;
  message: string;
  message_code: string | null;
  data: T | null;
}

const http = axios.create({ baseURL: API_BASE });

/** List the .docx documents available in the source-templates folder. */
export async function listDocuments(): Promise<DocumentListItem[]> {
  const { data } = await http.get<ApiResponse<DocumentListItem[]>>("/documents/list");
  return data.data ?? [];
}

/** Fetch a document's table of contents as a hierarchical tree. */
export async function getToc(documentPath: string): Promise<TocItem[]> {
  const { data } = await http.post<ApiResponse<TocItem[]>>("/documents/toc", {
    document_path: documentPath,
  });
  return data.data ?? [];
}

export interface MergeSectionPayload {
  master_template_path: string;
  source_document_path: string;
  source_start_bookmark: string;
  source_stop_bookmark: string | null;
  insert_before_bookmark: string | null;
  output_filename: string;
}

/** Merge a section (heading + descendants) into a copy of the master. */
export async function mergeSection(payload: MergeSectionPayload): Promise<ApiResponse<MergeResult>> {
  const { data } = await http.post<ApiResponse<MergeResult>>("/documents/merge-section", payload);
  return data;
}

/** Same-origin URL that streams a .docx for preview. */
export function downloadUrl(path: string): string {
  return `${API_BASE}/documents/download?path=${encodeURIComponent(path)}`;
}

/** Fetch a document as a Blob (for the embedded viewer). */
export async function fetchDocxBlob(path: string): Promise<Blob> {
  const { data } = await http.get(`/documents/download`, {
    params: { path },
    responseType: "blob",
  });
  return data as Blob;
}

export interface InsertSectionPayload {
  document_path: string;
  insert_before_bookmark: string | null;
  title: string;
  content: string;
  level: number;
  highlight?: boolean;
  is_html?: boolean;
  track_in_history?: boolean;
  /** When true, write to a new copy (copy_name) and leave the original unchanged. */
  save_as_copy?: boolean;
  /** File name for the copy (required when save_as_copy is true). */
  copy_name?: string | null;
}

export interface InsertSectionResult {
  output_path: string;
  created_copy: boolean;
}

/** Insert a new heading and body content into a document. */
export async function insertSection(
  payload: InsertSectionPayload,
): Promise<ApiResponse<InsertSectionResult>> {
  const { data } = await http.post<ApiResponse<InsertSectionResult>>("/documents/sections", payload);
  return data;
}

export interface InsertContentPayload {
  document_path: string;
  section_bookmark: string;
  html_content: string;
  image_data?: string | null;
  image_caption?: string | null;
  image_width?: number | null;
  image_height?: number | null;
  highlight?: boolean;
  save_as_copy?: boolean;
  copy_name?: string | null;
  track_in_history?: boolean;
}

export interface InsertContentResult {
  output_path: string;
  created_copy: boolean;
}

/** Insert HTML content and/or image at the end of a section. */
export async function insertContent(
  payload: InsertContentPayload,
): Promise<ApiResponse<InsertContentResult>> {
  const { data } = await http.post<ApiResponse<InsertContentResult>>("/documents/content", payload);
  return data;
}
