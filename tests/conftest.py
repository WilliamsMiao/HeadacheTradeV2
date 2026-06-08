import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401
from app.db import Base


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    local = sessionmaker(bind=engine)
    with local() as db:
        yield db

