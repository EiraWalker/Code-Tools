"""Authenticate the existing index publisher with short-lived GitHub OIDC."""
import os
import re
import jwt

ISSUER = "https://token.actions.githubusercontent.com"


class PublisherAuth:
    def __init__(self, origin):
        self.audience = origin + "/snapshot-sync"
        self.repository = os.environ["CBM_SYNC_REPOSITORY"]
        self.repository_id = os.environ["CBM_SYNC_REPOSITORY_ID"]
        self.ref = os.environ.get("CBM_SYNC_REF", "refs/heads/main")
        workflow = os.environ.get("CBM_SYNC_WORKFLOW", ".github/workflows/code-index.yml")
        self.workflow_ref = self.repository + "/" + workflow + "@" + self.ref
        self.keys = jwt.PyJWKClient(ISSUER + "/.well-known/jwks", timeout=15)

    def verify(self, authorization):
        if not authorization.startswith("Bearer ") or len(authorization) > 16384:
            raise ValueError("Missing publisher identity")
        token = authorization[7:]
        # Never select algorithms, issuer, or JWKS URL from an untrusted JWT.
        key = self.keys.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER,
                            audience=self.audience, options={"require": ["exp", "iat", "nbf", "sub"]})
        expected = {"repository": self.repository, "repository_id": self.repository_id,
                    "ref": self.ref, "workflow_ref": self.workflow_ref,
                    "sub": "repo:" + self.repository + ":ref:" + self.ref}
        if any(str(claims.get(k, "")) != v for k, v in expected.items()):
            raise ValueError("Publisher is outside the configured workflow scope")
        if claims.get("event_name") not in {"push", "workflow_dispatch"}:
            raise ValueError("Unsupported publisher event")
        if not re.fullmatch(r"[a-f0-9]{40}", claims.get("sha", "")):
            raise ValueError("Missing publisher commit")
        number, attempt = int(claims["run_number"]), int(claims["run_attempt"])
        if number < 1 or attempt < 1:
            raise ValueError("Invalid publisher run")
        return claims


def validate_identity(identity, maximum):
    if not isinstance(identity, dict):
        raise ValueError("Invalid snapshot identity")
    for field, pattern in (("sha256", r"[a-f0-9]{64}"), ("blob_sha", r"[a-f0-9]{40}"),
                           ("source_commit", r"[a-f0-9]{40}")):
        if not isinstance(identity.get(field), str) or not re.fullmatch(pattern, identity[field]):
            raise ValueError("Invalid snapshot identity")
    if type(identity.get("size_bytes")) is not int or not 16 <= identity["size_bytes"] <= maximum:
        raise ValueError("Invalid snapshot size")
    return identity
