export type LocalizedText = { en: string; fr: string };

/** UI contract for the future CV-backed, tenant-scoped repository. */
export interface PoolProfile {
  id: string;
  name: string;
  title: LocalizedText;
  location: string;
  email: string | null;
  phone: string | null;
  photo: { url: string; source: 'cv' | 'illustration' } | null;
  experienceYears: number;
  availability: 'available' | 'discuss';
  summary: LocalizedText;
  skills: Array<{ name: string; evidence: LocalizedText }>;
  experience: Array<{ role: LocalizedText; company: string; period: string; description: LocalizedText }>;
  education: Array<{ degree: LocalizedText; school: string; year: string }>;
  languages: string[];
  sourceCv: { filename: string; updatedAt: string; pageCount: number };
}

export interface InterviewDraft {
  profileId: string;
  recipient: string;
  subject: string;
  project: string;
  duration: string;
  message: string;
}

export interface ContactDraft {
  profileId: string;
  recipient: string;
  subject: string;
  message: string;
}

export interface PoolOffer {
  id: string;
  title: LocalizedText;
  company: string;
  location: string;
  description: LocalizedText;
  skills: string[];
}
