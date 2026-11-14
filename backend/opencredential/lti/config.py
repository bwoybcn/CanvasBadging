# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canvas LTI 1.3 developer-key configuration (paste JSON) for this deployment (ADR-0009).

Course Navigation only, ``default: disabled`` so each course opts in (open question Q15), and
the two custom variables the adapter needs to call the REST API.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from opencredential.lti.keys import public_jwk
from opencredential.settings import Settings

DEFAULT_LABEL = "Micro-Credentials"
NRPS_SCOPE = "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"


def endpoints(settings: Settings) -> dict[str, str]:
    base = settings.public_base_url.rstrip("/")
    return {
        "login": f"{base}/lti/login",
        "launch": f"{base}/lti/launch",
        "verify": f"{base}/lti/verify",
        "jwks": f"{base}/lti/jwks",
        "oauth_callback": f"{base}/api/v1/canvas/oauth/callback",
    }


def canvas_tool_config(
    settings: Settings,
    *,
    label: str = DEFAULT_LABEL,
    privacy_level: str = "public",
    include_public_jwk: bool = True,
) -> dict[str, Any]:
    ep = endpoints(settings)
    domain = urlsplit(settings.public_base_url).netloc
    config: dict[str, Any] = {
        "title": "OpenCredential",
        "description": "Micro-credentials and Open Badges 3.0 for Canvas courses.",
        "oidc_initiation_url": ep["login"],
        "target_link_uri": ep["launch"],
        "scopes": [NRPS_SCOPE],
        "extensions": [
            {
                "domain": domain,
                "tool_id": "opencredential",
                "platform": "canvas.instructure.com",
                "privacy_level": privacy_level,
                "settings": {
                    "text": label,
                    "placements": [
                        {
                            "placement": "course_navigation",
                            "message_type": "LtiResourceLinkRequest",
                            "target_link_uri": ep["launch"],
                            "text": label,
                            "default": "disabled",
                            "visibility": "members",
                            "windowTarget": "_self",
                        }
                    ],
                },
            }
        ],
        "custom_fields": {
            "canvas_course_id": "$Canvas.course.id",
            "canvas_user_id": "$Canvas.user.id",
            # The (sub-)account the course sits in, to place it in a linked area.
            "canvas_account_id": "$Canvas.account.id",
            # The student ID number (SIS user id), so providers can award badges from a list.
            "canvas_user_sis_id": "$Person.sourcedId",
        },
    }
    if include_public_jwk:
        config["public_jwk"] = public_jwk(settings)
    else:
        config["public_jwk_url"] = ep["jwks"]
    return config
