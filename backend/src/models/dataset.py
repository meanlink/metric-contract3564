from sqlalchemy import String, JSON, Double, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Dataset(Base):
    __tablename__ = 'datasets'
    __table_args__ = (UniqueConstraint('parent_id', 'supplement_hash', name='uq_datasets_supplement'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[float] = mapped_column(Double)
    # 补账追溯：源批次 -> 补账批次，原批次记录永不原地修改。
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default='base', server_default='base')
    supplement_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merge_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
