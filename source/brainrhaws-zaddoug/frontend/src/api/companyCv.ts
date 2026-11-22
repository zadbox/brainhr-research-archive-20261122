import { API_BASE_URL } from './client';

export type CompanyCvGenerationResult = {
  blob: Blob;
  filename: string | null;
  renderFingerprint: string | null;
  templateId: string | null;
  templateName: string | null;
  templateVersion: number | null;
  renderer: string | null;
  rendererVersion: string | null;
};

type CompanyCvGenerationJobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

type CompanyCvGenerationJob = {
  job_id: string;
  kind: string;
  status: CompanyCvGenerationJobStatus;
  created_at: string;
  updated_at: string;
  error: string | null;
  result: {
    filename?: string | null;
    render_fingerprint?: string | null;
    template_id?: string | null;
    template_name?: string | null;
    template_version?: number | null;
    renderer?: string | null;
    renderer_version?: string | null;
  } | null;
};

const JOB_POLL_INTERVAL_MS = 5000;
const JOB_POLL_ATTEMPTS = 120;

function buildGenerationPayload(templateId?: string, generationGuidance?: string): Record<string, string> {
  return {
    ...(templateId ? { template_id: templateId } : {}),
    ...(generationGuidance?.trim() ? { generation_guidance: generationGuidance.trim() } : {}),
  };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function responseError(response: Response, fallbackMessage: string): Promise<Error> {
  const text = await response.text();
  if (text) {
    try {
      const payload = JSON.parse(text) as { detail?: string; message?: string };
      return new Error(payload.message || payload.detail || fallbackMessage);
    } catch {
      return new Error(text);
    }
  }
  return new Error(fallbackMessage);
}

async function parseCompanyCvGenerationResponse(response: Response): Promise<CompanyCvGenerationResult> {
  if (!response.ok) {
    throw await responseError(response, 'Unable to generate company CV');
  }

  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || undefined;
  const match = disposition?.match(/filename="?([^";]+)"?/i);
  const rawTemplateVersion = response.headers.get('x-company-cv-template-version');
  const parsedTemplateVersion = rawTemplateVersion ? Number(rawTemplateVersion) : null;

  return {
    blob,
    filename: match?.[1] || null,
    renderFingerprint: response.headers.get('x-company-cv-render-fingerprint'),
    templateId: response.headers.get('x-company-cv-template-id'),
    templateName: response.headers.get('x-company-cv-template-name'),
    templateVersion: Number.isFinite(parsedTemplateVersion) ? parsedTemplateVersion : null,
    renderer: response.headers.get('x-company-cv-renderer'),
    rendererVersion: response.headers.get('x-company-cv-renderer-version'),
  };
}

async function parseCompanyCvGenerationJob(response: Response): Promise<CompanyCvGenerationJob> {
  if (!response.ok) {
    throw await responseError(response, 'Unable to read company CV generation status');
  }
  return response.json() as Promise<CompanyCvGenerationJob>;
}

async function startGenerationJob(
  sheetId: string,
  path: string,
  templateId?: string,
  generationGuidance?: string
): Promise<CompanyCvGenerationJob> {
  const response = await fetch(`${API_BASE_URL}/api/v1/interview-sheet/${sheetId}/${path}/jobs`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(buildGenerationPayload(templateId, generationGuidance)),
  });
  return parseCompanyCvGenerationJob(response);
}

async function getGenerationJob(
  sheetId: string,
  path: string,
  jobId: string
): Promise<CompanyCvGenerationJob> {
  const response = await fetch(`${API_BASE_URL}/api/v1/interview-sheet/${sheetId}/${path}/jobs/${jobId}`, {
    credentials: 'include',
  });
  return parseCompanyCvGenerationJob(response);
}

async function downloadGenerationJob(
  sheetId: string,
  path: string,
  jobId: string
): Promise<CompanyCvGenerationResult> {
  const response = await fetch(`${API_BASE_URL}/api/v1/interview-sheet/${sheetId}/${path}/jobs/${jobId}/download`, {
    credentials: 'include',
  });
  return parseCompanyCvGenerationResponse(response);
}

async function waitForGenerationJob(sheetId: string, path: string, job: CompanyCvGenerationJob): Promise<CompanyCvGenerationJob> {
  let current = job;
  for (let attempt = 0; attempt < JOB_POLL_ATTEMPTS; attempt += 1) {
    if (current.status === 'succeeded') {
      return current;
    }
    if (current.status === 'failed') {
      throw new Error(current.error || 'Unable to generate company CV');
    }
    await delay(JOB_POLL_INTERVAL_MS);
    current = await getGenerationJob(sheetId, path, current.job_id);
  }
  throw new Error('Company CV generation is still running. Please try again in a few minutes.');
}

async function generateWithJob(
  sheetId: string,
  path: string,
  templateId?: string,
  generationGuidance?: string
): Promise<CompanyCvGenerationResult> {
  const job = await startGenerationJob(sheetId, path, templateId, generationGuidance);
  const completedJob = await waitForGenerationJob(sheetId, path, job);
  return downloadGenerationJob(sheetId, path, completedJob.job_id);
}

export const companyCvApi = {
  generateFromInterviewSheet: async (
    sheetId: string,
    templateId?: string,
    generationGuidance?: string
  ): Promise<CompanyCvGenerationResult> => {
    return generateWithJob(sheetId, 'company-cv/html-docx', templateId, generationGuidance);
  },
};
