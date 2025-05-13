from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy import create_engine
from fastapi import Depends

DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    role = Column(String)  # z. B. "admin" oder "user"
    money = Column(Float, default=0)  # money of user

def create_user(db: Session, username: str, role: str):
    db_user = User(username=username, role=role)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_user(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
