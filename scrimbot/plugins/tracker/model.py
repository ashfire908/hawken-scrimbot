# -*- coding: utf-8 -*-

from enum import IntEnum, unique
from sqlalchemy import Column, ForeignKey, String, Integer, Boolean, DateTime, types
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


# Database enums
@unique
class LinkStatus(IntEnum):
    none = 0
    pending = 1
    linked = 2


class NativeIntEnum(types.TypeDecorator):
    """Converts between a native enum and a database integer"""
    impl = Integer

    def __init__(self, enum):
        self.enum = enum
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return value.value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self.enum(value)


class Player(Base):
    __tablename__ = "players"

    id = Column(String(36), primary_key=True)
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    link_user = Column(Integer, ForeignKey("users.id"), index=True)
    link_status = Column(NativeIntEnum(LinkStatus), default=LinkStatus.none, nullable=False)
    opt_out = Column(Boolean, default=False, nullable=False)
    blacklisted = Column(Boolean, default=False, nullable=False)
    blacklist_reason = Column(String)
    blacklist_by = Column(Integer, ForeignKey("users.id"))

    user = relationship("User", foreign_keys=[link_user], uselist=False, backref="players")
    blacklister = relationship("User", foreign_keys=[blacklist_by])

    def __repr__(self):
        return "<Player(id='{0}')>".format(self.id)

    def update(self, poll_time):
        if self.first_seen is None:
            self.first_seen = poll_time
        self.last_seen = poll_time


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, autoincrement=True, primary_key=True)
    username = Column(String, unique=True, nullable=False)

    def __repr__(self):
        return "<User(id={0}, username='{1}')>".format(self.id, self.username)
