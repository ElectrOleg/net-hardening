"""User model — local and LDAP-backed accounts."""
import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


class User(db.Model):
    """HCS user account.

    auth_source:
        'local'  — password stored in DB (bcrypt)
        'ldap'   — password verified against AD; password_hash is NULL

    role:
        'admin'    — full access, user/settings management
        'operator' — can run scans, manage rules/exceptions
        'viewer'   — read-only access to dashboards/reports
    """

    __tablename__ = "hcs_users"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = db.Column(db.String(100), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(200), default="")
    email = db.Column(db.String(200), default="")
    password_hash = db.Column(db.String(256), nullable=True)  # NULL for LDAP users

    auth_source = db.Column(db.String(20), nullable=False, default="local")  # local | ldap
    role = db.Column(db.String(20), nullable=False, default="viewer")  # admin | operator | viewer

    is_active = db.Column(db.Boolean, default=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f"<User {self.username} ({self.auth_source}/{self.role})>"

    # ── Password helpers ───────────────────────────────────────────

    def set_password(self, plain: str):
        """Hash and store password (local users only)."""
        self.password_hash = generate_password_hash(plain, method="pbkdf2:sha256")

    def check_password(self, plain: str) -> bool:
        """Verify password against stored hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, plain)

    # ── Serialization ──────────────────────────────────────────────

    def to_dict(self):
        return {
            "id": str(self.id),
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "auth_source": self.auth_source,
            "role": self.role,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
