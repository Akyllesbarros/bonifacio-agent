"""
Database – SQLite via SQLAlchemy async
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Text, DateTime, Boolean, ForeignKey, func, text
from datetime import datetime
from typing import Optional, List

DATABASE_URL = "sqlite+aiosqlite:///./bonifacio.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


# ────────────────────────────────────────────────
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # AI control
    ai_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Qualification stage
    # 0=start, 1=waiting_name, 2=waiting_invest, 3=waiting_value, 4=completed
    stage: Mapped[int] = mapped_column(Integer, default=0)
    investment_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_tier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Agendor IDs
    agendor_person_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agendor_deal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agendor_salesperson_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Contact management (for test + audit)
    contact_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reset_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",   # cascade deletes messages when contact is deleted
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    direction: Mapped[str] = mapped_column(String(3))   # "in" | "out"
    content: Mapped[str] = mapped_column(Text)
    wa_message_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class AppSetting(Base):
    """Key/value store for runtime settings (overrides env, stored in DB)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class SalespersonRotation(Base):
    """Tracks the round-robin pointer per value tier."""
    __tablename__ = "salesperson_rotation"

    tier: Mapped[str] = mapped_column(String(50), primary_key=True)
    next_index: Mapped[int] = mapped_column(Integer, default=0)


# ────────────────────────────────────────────────
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migration-safe: add new columns if they don't exist (SQLite doesn't support IF NOT EXISTS for columns)
        for col_sql in [
            "ALTER TABLE conversations ADD COLUMN contact_notes TEXT",
            "ALTER TABLE conversations ADD COLUMN reset_count INTEGER DEFAULT 0",
        ]:
            try:
                await conn.execute(text(col_sql))
            except Exception:
                pass  # column already exists – that's fine


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
