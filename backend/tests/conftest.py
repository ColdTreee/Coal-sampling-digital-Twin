import sys
import os
from pathlib import Path

os.environ["ENVIRONMENT"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".runtime-deps"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app as fastapi_app
from app.auth.security import AuthenticatedUser, create_token, hash_password
from app.models import Role, User, user_roles


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        roles = {name: Role(name=name, description=name) for name in ("administrator", "operator", "readonly")}
        session.add_all(roles.values())
        users = {
            name: User(username="test-" + name, password_hash=hash_password("test-password-" + name))
            for name in roles
        }
        session.add_all(users.values())
        session.flush()
        for name, user in users.items():
            session.execute(user_roles.insert().values(user_id=user.id, role_id=roles[name].id))
        session.commit()
        tokens = {name: create_token(user, [name]) for name, user in users.items()}

    def override_get_db():
        with session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app, headers={"Authorization": f"Bearer {tokens['administrator']}"}) as test_client:
        test_client.role_tokens = tokens
        yield test_client
    fastapi_app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
