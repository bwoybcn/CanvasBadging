# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models for the spec §12 domain. Importing this package registers every table."""

from opencredential.db.models.audit import AuditEvent, background_jobs
from opencredential.db.models.authoring import (
    AchievementDefinition,
    AchievementVersion,
    AwardRule,
    AwardRuleSet,
    BadgeAsset,
    BadgeTemplate,
    DefinitionReview,
    ManualRuleApproval,
)
from opencredential.db.models.awards import (
    AwardDecision,
    Credential,
    CredentialEvidence,
    CredentialStatus,
    CredentialStatusEvent,
    EligibilityEvaluation,
    RevocationRequest,
    ShareGrant,
    StatusList,
    StatusListBit,
)
from opencredential.db.models.identity import (
    Course,
    ExternalIdentity,
    Membership,
    OrgUnit,
    User,
)
from opencredential.db.models.issuers import Issuer, IssuerDelegation, IssuerKey
from opencredential.db.models.lms import (
    LmsAssignment,
    LmsModule,
    LmsModuleProgress,
    LmsSubmission,
    SyncRun,
)
from opencredential.db.models.tenancy import (
    CanvasIntegration,
    CanvasToken,
    Institution,
    LtiDeployment,
    LtiLaunchState,
    LtiNonceUsed,
)

__all__ = [
    "AchievementDefinition",
    "AchievementVersion",
    "AuditEvent",
    "AwardDecision",
    "AwardRule",
    "AwardRuleSet",
    "BadgeAsset",
    "BadgeTemplate",
    "CanvasIntegration",
    "CanvasToken",
    "Course",
    "Credential",
    "CredentialEvidence",
    "CredentialStatus",
    "CredentialStatusEvent",
    "DefinitionReview",
    "EligibilityEvaluation",
    "ExternalIdentity",
    "Institution",
    "Issuer",
    "IssuerDelegation",
    "IssuerKey",
    "LmsAssignment",
    "LmsModule",
    "LmsModuleProgress",
    "LmsSubmission",
    "LtiDeployment",
    "LtiLaunchState",
    "LtiNonceUsed",
    "ManualRuleApproval",
    "Membership",
    "OrgUnit",
    "RevocationRequest",
    "ShareGrant",
    "StatusList",
    "StatusListBit",
    "SyncRun",
    "User",
    "background_jobs",
]
