import type { Enterprise, Project } from '../../api/types';

export interface SearchCandidate {
  id: string;
  name: string;
  title: string;
  filename: string;
  projectId: string;
  projectName: string;
  companyName: string;
}

export interface SearchIndex {
  projects: Project[];
  enterprises: Enterprise[];
  candidates: SearchCandidate[];
  failedCandidateProjects: number;
}

export type SearchResult =
  | { kind: 'candidate'; id: string; primary: string; secondary: string; href: string }
  | { kind: 'project'; id: string; primary: string; secondary: string; href: string }
  | { kind: 'company'; id: string; primary: string; secondary: string; href: string };

export type SearchStatus = 'idle' | 'loading' | 'ready' | 'error';
