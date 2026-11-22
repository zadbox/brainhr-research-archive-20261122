"""
Modèles SQLModel pour Brain RH
Architecture hybride : tables DB = index, JSON = données complètes
"""

from .enterprise import EnterpriseDB
from .project import ProjectDB
from .cv import CVMetaDB
from .interview_sheet import InterviewSheetDB
from .realtime_interview import RealtimeInterviewDB
from .interview_appointment import InterviewAppointmentDB, InterviewAppointmentStatus
from .auth import (
    AccessGrantDB,
    AccessScopeKind,
    InvitationScopeKind,
    InvitationStatus,
    MembershipDB,
    TenantDB,
    UserDB,
    UserInvitationDB,
    UserRole,
)
from .audit_log import AuditLogDB
from .talent_profile import TalentProfileDB
from .resume_version import ResumeVersionDB
from .application import ApplicationDB
from .tenant_cv_template import TenantCvTemplateDB
from .llm_settings import LLMProcessSettingDB
from .integration import (
    ConnectorScopePolicyDB,
    IntegrationAccountDB,
    WebhookSubscriptionDB,
    OutboundEventDB,
    DeliveryAttemptDB,
    ConnectorStatus,
    ConnectorScopePolicy,
    IntegrationScopeKind,
    EventStatus,
    DeliveryStatus,
)
from .turnover_it import TurnoverApplicationInboxDB, TurnoverJobPublicationDB
from .crustdata import (
    CrustdataCriteriaDB,
    CrustdataCreditOperationDB,
    CrustdataIdentityDB,
    CrustdataIdentityEnterpriseDB,
    CrustdataSearchResultDB,
    CrustdataSearchSessionDB,
    CrustdataWalletDB,
)

__all__ = [
    "EnterpriseDB",
    "ProjectDB",
    "CVMetaDB",
    "InterviewSheetDB",
    "RealtimeInterviewDB",
    "InterviewAppointmentDB",
    "InterviewAppointmentStatus",
    "TenantDB",
    "UserDB",
    "MembershipDB",
    "AccessGrantDB",
    "AccessScopeKind",
    "UserRole",
    "UserInvitationDB",
    "InvitationScopeKind",
    "InvitationStatus",
    "AuditLogDB",
    "TalentProfileDB",
    "ResumeVersionDB",
    "ApplicationDB",
    "TenantCvTemplateDB",
    "LLMProcessSettingDB",
    "IntegrationAccountDB",
    "ConnectorScopePolicyDB",
    "WebhookSubscriptionDB",
    "OutboundEventDB",
    "DeliveryAttemptDB",
    "ConnectorStatus",
    "ConnectorScopePolicy",
    "IntegrationScopeKind",
    "EventStatus",
    "DeliveryStatus",
    "TurnoverApplicationInboxDB",
    "TurnoverJobPublicationDB",
    "CrustdataCriteriaDB",
    "CrustdataCreditOperationDB",
    "CrustdataIdentityDB",
    "CrustdataIdentityEnterpriseDB",
    "CrustdataSearchResultDB",
    "CrustdataSearchSessionDB",
    "CrustdataWalletDB",
]
