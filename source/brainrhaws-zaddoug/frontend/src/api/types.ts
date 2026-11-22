// Types pour l'API Brain RH

export interface Contact {
  nom_complet: string;
  poste?: string;
  email: string;
  telephone?: string;
  canal_prefere?: 'email' | 'telephone' | 'slack' | 'autre';
  notes?: string;
}

export interface Enterprise {
  id: string;
  tenant_id?: string | null;
  tenant_name?: string | null;
  nom: string;
  site_web?: string;
  secteur?: string;
  notes?: string;
  contacts: Contact[];
  cv_templates?: CompanyCvTemplate[];
  created_at?: string;
  last_modified?: string;
  projects_count: number;
}

export interface AdminClient {
  id: string;
  name: string;
  created_at: string;
  trial_duration_days?: number | null;
  trial_started_at?: string | null;
  trial_expires_at?: string | null;
  trial_status?: 'pending' | 'active' | 'expired' | null;
}

export interface CompanyCvTemplate {
  id: string;
  tenant_id?: string | null;
  scope_kind?: string | null;
  name: string;
  original_filename: string;
  version: number;
  detected_variables: string[];
  resolved_placeholders: string[];
  unknown_placeholders: string[];
  ambiguous_placeholders: string[];
  unsupported_variables: string[];
  supported_context_roots: string[];
  example_placeholders: string[];
  mapping_version?: string | null;
  mapper_version?: string | null;
  render_mode?: string | null;
  layout_spec_version?: string | null;
  layout_spec_status?: string | null;
  layout_spec?: CompanyCvTemplateLayoutSpec | null;
  layout_spec_errors?: string[];
  layout_spec_warnings?: string[];
  is_valid: boolean;
  is_active: boolean;
  created_at: string;
  activated_at?: string | null;
}

export interface CompanyCvTemplateCandidate {
  candidate_id: string;
  source: string;
  anchor_type: string;
  anchor: string;
  section_name_hint?: string;
  render_type_hint?: string;
  inside_fixed_container?: boolean;
  confidence?: string;
  placeholders?: string[];
  preview_text?: string;
}

export interface CompanyCvTemplateSectionSpec {
  required: boolean;
  render_type: string;
  bounded: boolean;
  max_items?: number | null;
  anchor?: string;
  anchor_type?: string;
  candidate_id?: string;
  style_source?: string;
  confirmed?: boolean;
  inside_fixed_container?: boolean;
  placeholders?: string[];
}

export interface CompanyCvTemplateLayoutSpec {
  version: string;
  page?: Record<string, unknown>;
  shell?: Record<string, unknown>;
  branding?: Record<string, unknown>;
  supported_sections?: Record<string, CompanyCvTemplateSectionSpec>;
  candidates?: CompanyCvTemplateCandidate[];
  confirmed_mappings?: Record<string, { candidate_id: string; render_type: string; style_source?: string }>;
  sections?: Record<string, CompanyCvTemplateSectionSpec>;
  rules?: Record<string, unknown>;
}

export interface Project {
  id: string;
  nom: string;
  enterprise_id?: string;
  service_demandeur?: string;
  responsable_offre?: string;
  contact_responsable?: string;
  notes?: string;
  description?: string;
  created_at: string;
  last_modified: string;
  status: 'actif' | 'archive';
  updated_at?: string;
}

export interface ProjectCandidateSummary {
  count: number;
  ready: boolean;
  enterprise_name?: string | null;
}

export type CVExperience = Record<string, unknown>;
export type CVFormation = Record<string, unknown>;
export type CVProjectItem = Record<string, unknown> | string;

export interface CV {
  cv: string;
  project_id?: string;
  enterprise_id?: string;
  enterprise_nom?: string;
  identite?: {
    nom?: string;
    prenom?: string;
    email?: string;
    telephone?: string;
    adresse?: string;
  };
  titre?: string;
  resume_professionnel?: string;
  competences_techniques: string[];
  competences_transversales: string[];
  langues: string[];
  experience?: Array<{
    entreprise?: string;
    poste?: string;
    date_debut?: string;
    date_fin?: string;
    description?: string;
  }>;
  experiences_professionnelles: CVExperience[];
  formations: CVFormation[];
  certifications: string[];
  projets: CVProjectItem[];
}

export interface Offre {
  sections: {
    titre?: string;
    description?: string;
    resume_professionnel?: string;
    competences_techniques: string[];
    competences_transversales: string[];
    outils?: string[];
    langages?: string[];
    langues: string[];
    experiences_professionnelles: CVExperience[];
    formations: CVFormation[];
    certifications: string[];
    projets: CVProjectItem[];
  };
  must_have: string[];
  nice_have: string[];
  source_text?: string;
  source_file_name?: string | null;
}

export interface Evidence {
  id: string;
  type: 'section' | 'json_path' | 'quote' | string;
  ref: string;
}

export interface EvidenceMap {
  commentaire_scoring?: string[];
  appreciation_globale?: string[];
}

export interface Gap {
  period: string;
  duration_months: number;
  between: string;
}

export interface Overlap {
  overlap_period: string;
  overlap_days: number;
  experiences: string;
  same_company: boolean;
}

export interface Flags {
  gappes?: Gap[];
  overlaps?: Overlap[];
}

export interface CriterionAssessment {
  criterion: string;
  status: 'met' | 'partial' | 'missing' | 'unclear' | string;
  reason?: string;
  evidence_ids?: string[];
}

export interface AlgorithmicWeights {
  exp?: number | null;
  tech?: number | null;
  summary?: number | null;
  soft?: number | null;
}

export interface AlgorithmicBreakdown {
  mode: 'sectioned' | 'global' | string;
  score_base: number;
  final_algorithmic_score_before_rerank_coefficient: number;
  tech_score?: number | null;
  experience_score_raw?: number | null;
  experience_score_effective?: number | null;
  summary_score?: number | null;
  soft_score?: number | null;
  weights?: AlgorithmicWeights;
  nice_to_have_missing_count: number;
  nice_to_have_multiplier: number;
}

export interface ResultatMatching {
  cv: string;
  candidate_name?: string;
  score_final: number;
  score_base: number;
  bonus_nice_have_multiplicateur: number;
  coefficient_qualite_experience: number;
  nice_have_manquants: string[];
  commentaire_scoring?: string;
  appreciation_globale?: string;
  evidences?: Evidence[];
  evidence_map?: EvidenceMap;
  flags?: Flags;
  original_cv_url?: string | null;
  matrix_summary?: string;
  recommendation_level?: 'strong_fit' | 'good_fit' | 'mixed' | 'weak_fit' | string;
  relevant_experience_years?: number | null;
  top_strengths?: string[];
  watchouts?: string[];
  interview_focus?: string[];
  must_have_assessment?: CriterionAssessment[];
  nice_have_assessment?: CriterionAssessment[];
  algorithmic_rank?: number | null;
  reranked?: boolean | null;
  algorithmic_breakdown?: AlgorithmicBreakdown | null;
}

export interface MatchingResponse {
  results: ResultatMatching[];
  qualified_results?: ResultatMatching[];
  metadata: {
    total_cvs: number;
    filtered_must_have: number;
    top_reranked: number;
    qualified_pool_count?: number;
    duree_totale_s: number;
    must_have_criteria_count?: number | null;
    must_have_skipped?: boolean | null;
    must_have_provider_used?: string | null;
    must_have_model_used?: string | null;
    must_have_duration_s?: number | null;
    must_have_fallback_used?: boolean | null;
    nice_have_provider_used?: string | null;
    nice_have_model_used?: string | null;
    nice_have_duration_s?: number | null;
    nice_have_fallback_used?: boolean | null;
    reranking_provider_used?: string | null;
    reranking_model_used?: string | null;
    reranking_reasoning_effort_used?: string | null;
    reranking_duration_s?: number | null;
    reranking_attempt_count?: number | null;
    reranking_fallback_used?: boolean | null;
    timestamp?: string;
  };
}

export interface CVParseResult {
  success: boolean;
  cv?: string;
  filename?: string;
  data?: CV;
  error?: string;
}

export interface CVParseResponse {
  success_count: number;
  failed_count: number;
  total: number;
  duree_totale_s: number;
  results: CVParseResult[];
}

// SSE Events
export interface SSEProgressEvent {
  step: string;
  current: number;
  total: number;
  progress: number;
  message: string;
  skipped?: boolean;
  criteria_count?: number;
}

export interface SSEResultEvent {
  success: boolean;
  cv?: string;
  data?: unknown;
  error?: string;
}

export interface SSEDoneEvent {
  summary: {
    results?: unknown[];
    metadata?: Record<string, unknown>;
    success_count?: number;
    failed_count?: number;
    total?: number;
  };
}

export interface SSEErrorEvent {
  code: string;
  message: string;
  traceback?: string;
}

export interface APIError {
  code: string;
  message: string;
  details?: unknown;
}

export interface ProjectHistory {
  total: number;
  items: {
    matching_id: string;
    timestamp: string;
    candidats_count: number;
  }[];
}

// Enrichissement d'offres
export interface EnrichmentCompetence {
  name: string;
  type: 'must' | 'nice';
  source: string;
  rationale: string;
}

export interface EnrichmentItem {
  name: string;
  rationale: string;
}

export interface EnrichmentMission {
  text: string;
  rationale: string;
}

export interface EnrichmentPropositions {
  competences: EnrichmentCompetence[];
  outils: EnrichmentItem[];
  langages: EnrichmentItem[];
  certifications: EnrichmentItem[];
  missions: EnrichmentMission[];
  questions_clarification: string[];
}

export interface EnrichmentResult {
  coverage_score: number;
  propositions: EnrichmentPropositions;
}

export interface EnrichmentSelections {
  competences: number[];
  outils: number[];
  langages: number[];
  certifications: number[];
  missions: number[];
}

export interface QuestionResponses {
  [question: string]: string;
}

// ==========================================
// Intégrations (INTEG-008)
// ==========================================

export interface Connector {
  id: string;
  name: string;
  family: string;
  capabilities: string[];
  description: string;
  is_available: boolean;
  scope_policy: ConnectorScopePolicy;
  policy_source: 'default' | 'database' | 'enforced';
  setup_state?: 'configuration_required' | 'authorization_unavailable' | null;
  oauth_start_available?: boolean | null;
}

export type ConnectorScopePolicy = 'client_only' | 'platform_only' | 'client_or_platform';
export type IntegrationScopeKind = 'client' | 'platform' | 'enterprise_legacy';

export interface IntegrationAccount {
  id: string;
  enterprise_id: string | null;
  tenant_id: string | null;
  scope_kind: IntegrationScopeKind;
  scope_id: string;
  connector_id: string;
  status: 'active' | 'inactive' | 'error';
  config_json: string;
  created_at: string;
  updated_at: string;
}

export interface IntegrationAccountCreate {
  connector_id: string;
  scope_kind: 'client' | 'platform';
  tenant_id?: string;
  config: Record<string, unknown>;
  secret_ref?: string;
  status?: 'active' | 'inactive';
}

export interface OutlookOAuthConfiguration {
  connector_id: 'outlook';
  scope_policy: 'client_only';
  setup_state: 'configuration_required' | 'authorization_unavailable';
  oauth_start_available: boolean;
}

export interface IntegrationEvent {
  id: string;
  enterprise_id: string;
  event_type: string;
  status: 'pending' | 'delivered' | 'failed' | 'retrying';
  retry_count: number;
  created_at: string;
}

export interface TurnoverConfiguration {
  connector_id: 'turnover_it';
  tenant_id: string;
  configured: boolean;
  status: 'active' | 'inactive' | 'error';
  api_base_url: string;
  updated_at?: string | null;
}

export interface TurnoverConnectionTest {
  connected: boolean;
  status_code?: number | null;
  message: string;
}

export type TurnoverContract =
  | 'PERMANENT'
  | 'TEMPORARY'
  | 'FREELANCE'
  | 'INTERNSHIP'
  | 'APPRENTICESHIP'
  | 'INTERCONTRACT';

export type TurnoverRemote = 'NONE' | 'PARTIAL' | 'FULL';

export interface TurnoverPublication {
  id: string;
  tenant_id: string;
  project_id: string;
  contract: TurnoverContract;
  remote: TurnoverRemote;
  country: string;
  region?: string | null;
  postal_code?: string | null;
  requested_status: string;
  status: 'pending' | 'published' | 'failed' | 'retrying';
  callback_url: string;
  remote_public_url?: string | null;
  remote_job_id?: string | null;
  application_count: number;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TurnoverPublicationCreate {
  project_id: string;
  contract: TurnoverContract;
  remote: TurnoverRemote;
  country: string;
  region?: string;
  postal_code?: string;
  requested_status?: 'Draft' | 'Published';
}

export interface TurnoverApplicationSimulation {
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
}

export interface TurnoverApplicationReceipt {
  accepted: boolean;
  duplicate: boolean;
  application_id?: number | null;
}

// ---- Admin Users (ADMIN-FIX-001) ----
// Correspond exactement au contrat AdminUserResponse côté backend.
// platform_admin n'apparaît JAMAIS comme membership_role.
export interface AdminUser {
  id: string;
  email: string;
  global_role: 'platform_admin' | 'client_admin' | 'enterprise_admin' | 'project_manager' | 'recruiter' | 'viewer';
  membership_role: 'enterprise_admin' | 'recruiter' | 'viewer' | null;
  access_role: 'client_admin' | 'enterprise_admin' | 'project_manager' | 'recruiter' | 'viewer' | null;
  access_scope_kind: 'client' | 'enterprise' | 'project' | null;
  access_scope_id: string | null;
  enterprise_id: string | null;
  membership_id: string | null;
  is_user_active: boolean;
  is_membership_active: boolean | null;
  is_access_grant_active: boolean | null;
  invitation_id: string | null;
  invitation_status: 'pending_delivery' | 'sent' | 'delivery_failed' | 'accepted' | 'revoked' | 'expired' | null;
  invitation_expires_at: string | null;
  invitation_retry_after_seconds: number | null;
  invitation_first_name?: string | null;
  invitation_last_name?: string | null;
}

export interface InviteUserPayload {
  email: string;
  first_name: string;
  last_name: string;
  role: 'platform_admin' | 'client_admin' | 'enterprise_admin' | 'recruiter' | 'viewer';
  tenant_id?: string;
  language: 'en' | 'fr';
}

export interface InvitationState {
  status: 'ready' | 'accepted' | 'expired' | 'used' | 'invalid' | 'email_unavailable' | 'trial_expired';
  requires_password: boolean;
  expires_at: string | null;
  tenant_name?: string | null;
  trial_duration_days?: number | null;
  trial_started_at?: string | null;
  trial_expires_at?: string | null;
  trial_status?: 'pending' | 'active' | 'expired' | null;
}

export interface UpdateRolePayload {
  role: 'enterprise_admin' | 'recruiter' | 'viewer';
}

export interface UpdateStatusPayload {
  is_active: boolean;
}
