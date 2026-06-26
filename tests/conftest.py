import os
import sys

import pytest

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Set DATABASE_URL and AUTH_ENABLED for tests
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_app.db"))
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app import create_app, db
from app.models import ConfigSnapshot, Vendor
from app.models.user import User


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture(scope="session")
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF in tests for ease of testing

    with app.app_context():
        db.create_all()
        # Seed basic vendors
        v = Vendor(code="cisco_ios", name="Cisco IOS")
        db.session.add(v)
        db.session.commit()
        yield app

        db.session.remove()
        db.drop_all()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass


@pytest.fixture(scope="function")
def session(app):
    """Clean database session context per test case."""
    with app.app_context():
        # Clear existing dynamic data
        db.session.query(ConfigSnapshot).delete()
        db.session.query(User).delete()
        db.session.commit()
        yield db.session
        db.session.rollback()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(session):
    admin = User(username="admin", display_name="Admin", role="admin", is_active=True)
    admin.set_password("admin_pass")
    session.add(admin)
    session.commit()
    return admin


@pytest.fixture
def operator_user(session):
    operator = User(username="operator", display_name="Operator", role="operator", is_active=True)
    operator.set_password("operator_pass")
    session.add(operator)
    session.commit()
    return operator


@pytest.fixture
def viewer_user(session):
    viewer = User(username="viewer", display_name="Viewer", role="viewer", is_active=True)
    viewer.set_password("viewer_pass")
    session.add(viewer)
    session.commit()
    return viewer
