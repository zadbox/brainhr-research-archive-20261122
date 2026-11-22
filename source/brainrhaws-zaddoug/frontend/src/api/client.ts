import axios, { AxiosError } from 'axios';
import type { APIError } from './types';
import { publishInterviewScheduleUpdate } from '../lib/interviewScheduleUpdates';

type ErrorRecord = Record<string, unknown>;

function asErrorRecord(value: unknown): ErrorRecord | null {
  return value !== null && typeof value === 'object' ? value as ErrorRecord : null;
}

const DEV_API_PORT = '8000';

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/+$/, '');
}

function getDefaultApiBaseUrl(): string {
  if (typeof window === 'undefined') {
    return `http://localhost:${DEV_API_PORT}`;
  }

  const { hostname, origin, port, protocol } = window.location;
  const isLocalhost = hostname === 'localhost' || hostname === '127.0.0.1';

  if (isLocalhost && port !== DEV_API_PORT) {
    return `${protocol}//${hostname}:${DEV_API_PORT}`;
  }

  return origin;
}

// Base API URL (sans /api/v1 pour fichiers statiques)
const ENV_API_BASE = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = normalizeBaseUrl(ENV_API_BASE || getDefaultApiBaseUrl());

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  timeout: 300000, // 5 minutes (LLM calls)
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Intercepteur pour normaliser les erreurs
apiClient.interceptors.response.use(
  (response) => {
    const { method, url } = response.config;
    if (method && ['post', 'patch', 'put', 'delete'].includes(method.toLowerCase())
      && /^\/(interview-appointments|interview-sheet)(\/|$)/.test(url || '')) {
      publishInterviewScheduleUpdate();
    }
    return response;
  },
  (error: AxiosError<APIError>) => {
    if (error.response) {
      const publicAuthPage = ['/login', '/activate-invitation'].includes(window.location.pathname);
      if (error.response.status === 401 && !publicAuthPage) {
        window.location.href = '/login';
      }

      const responseData = asErrorRecord(error.response.data) ?? {};
      const detail = responseData.detail;
      const detailData = asErrorRecord(detail);
      const defaultCode = error.response.status === 401
        ? 'UNAUTHORIZED'
        : error.response.status === 400
          ? 'BAD_REQUEST'
          : 'SERVER_ERROR';
      const flatCode = typeof responseData.code === 'string' ? responseData.code : null;
      const nestedCode = typeof detailData?.code === 'string' ? detailData.code : null;
      const flatMessage = typeof responseData.message === 'string' ? responseData.message : null;
      const nestedMessage = typeof detailData?.message === 'string' ? detailData.message : null;
      const stringDetail = typeof detail === 'string' ? detail : null;
      const rawDetails = responseData.details ?? detailData?.details;
      const normalizedDetails = asErrorRecord(rawDetails);
      const apiError: APIError = {
        code: flatCode || nestedCode || defaultCode,
        message: flatMessage || nestedMessage || stringDetail || 'Une erreur est survenue',
        details: normalizedDetails
          ? { ...normalizedDetails, status: error.response.status }
          : { status: error.response.status },
      };
      return Promise.reject(apiError);
    } else if (error.request) {
      // No response (network)
      const apiError: APIError = {
        code: 'NETWORK_ERROR',
        message: 'Unable to contact the server. Check your connection.',
        details: { originalError: error.message },
      };
      return Promise.reject(apiError);
    } else {
      // Configuration error
      const apiError: APIError = {
        code: 'CLIENT_ERROR',
        message: error.message,
        details: {},
      };
      return Promise.reject(apiError);
    }
  }
);
