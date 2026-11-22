export interface CandidateIdentityLabel {
  nom_complet?: string | null;
  prenom?: string | null;
  nom?: string | null;
}

export interface CandidateLabelSource {
  candidateId: string;
  identity?: CandidateIdentityLabel | null;
}

const humanizeIdentifier = (identifier: string): string => {
  const basename = identifier.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '')?.trim() ?? '';
  if (!basename || /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(basename)
    || /^[0-9a-f]{16,}$/i.test(basename) || /^\d{8,}$/.test(basename)) {
    return '';
  }

  const words = basename.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();

  if (!words) {
    return '';
  }

  return words;
};

export const candidateLabel = (
  { candidateId, identity }: CandidateLabelSource,
  fallback = 'Candidate'
): string => {
  const fullName = identity?.nom_complet?.trim();
  if (fullName) {
    return fullName;
  }

  const splitName = [identity?.prenom?.trim(), identity?.nom?.trim()].filter(Boolean).join(' ');
  if (splitName) {
    return splitName;
  }

  return humanizeIdentifier(candidateId) || fallback;
};
