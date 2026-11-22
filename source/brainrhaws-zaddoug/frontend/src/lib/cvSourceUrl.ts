export function buildOpenCvHref(
  apiBaseUrl: string,
  originalCvUrl?: string | null,
  fallback?: string | null
): string | null {
  const path = originalCvUrl || fallback;
  if (!path) {
    return null;
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  if (path.startsWith('//')) {
    return path;
  }

  const hashIndex = path.indexOf('#');
  const hash = hashIndex >= 0 ? path.slice(hashIndex) : '';
  const pathWithoutHash = hashIndex >= 0 ? path.slice(0, hashIndex) : path;
  const queryIndex = pathWithoutHash.indexOf('?');
  const pathname = queryIndex >= 0 ? pathWithoutHash.slice(0, queryIndex) : pathWithoutHash;
  const query = queryIndex >= 0 ? pathWithoutHash.slice(queryIndex + 1) : '';
  const params = new URLSearchParams(query);
  params.set('proxy', 'true');
  params.set('download', '0');
  const normalizedPath = pathname.startsWith('/') ? pathname : `/${pathname}`;
  const normalizedBase = apiBaseUrl.endsWith('/') ? apiBaseUrl.slice(0, -1) : apiBaseUrl;

  return `${normalizedBase}${normalizedPath}?${params.toString()}${hash}`;
}
