from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class RetestBatch(Base):
    """复测用观察日表批次；occupied_by 非空即被某次签发占用（与凭证一并生效）。"""
    __tablename__ = 'retest_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='retest.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    occupied_by: Mapped[int | None] = mapped_column(ForeignKey('retest_vouchers.id'), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)


class RetestVoucher(Base):
    """独立复测凭证。pending=待签，issued=已签；同一原分析只允许一张已签凭证。"""
    __tablename__ = 'retest_vouchers'
    __table_args__ = (
        UniqueConstraint('request_key', name='uq_retest_request_key'),
        UniqueConstraint('origin_job_id', name='uq_retest_one_issued_per_origin'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    origin_job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    retest_batch_id: Mapped[int] = mapped_column(ForeignKey('retest_batches.id'))
    request_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    origin_result: Mapped[dict] = mapped_column(JSON, default=dict)
    retest_result: Mapped[dict] = mapped_column(JSON, default=dict)
    direction: Mapped[dict] = mapped_column(JSON, default=dict)
    overlap: Mapped[dict] = mapped_column(JSON, default=dict)
    filename: Mapped[str] = mapped_column(String(160), default='')
    checksum: Mapped[str] = mapped_column(String(64), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    issued_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
