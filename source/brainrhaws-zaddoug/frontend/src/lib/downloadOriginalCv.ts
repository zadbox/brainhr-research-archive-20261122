import { API_BASE_URL } from '../api/client';

function filenameFromContentDisposition(header: string | null): string | null {
  if (!header) {
    return null;
  }

  const encodedMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1]);
    } catch {
      return encodedMatch[1];
    }
  }

  const quotedMatch = header.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const plainMatch = header.match(/filename=([^;]+)/i);
  return plainMatch?.[1]?.trim() || null;
}

function originalFilenameFallback(cvFilename: string): string {
  return cvFilename.replace(/\.json$/i, '');
}

export async function downloadOriginalCv(originalCvUrl: string, cvFilename: string): Promise<string> {
  const separator = originalCvUrl.includes('?') ? '&' : '?';
  const downloadUrl = `${API_BASE_URL}${originalCvUrl}${separator}proxy=true`;
  const response = await fetch(downloadUrl, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const blob = await response.blob();
  const filename =
    filenameFromContentDisposition(response.headers.get('content-disposition')) ||
    originalFilenameFallback(cvFilename);
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);

  return filename;
}
