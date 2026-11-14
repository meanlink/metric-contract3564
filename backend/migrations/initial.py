from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 补账是在既有部署上升级的字段：create_all 不会修改已有表，这里做幂等 ALTER。
NEW_COLUMNS = {
    'datasets': [
        ('parent_id', 'INTEGER NULL'),
        ('kind', "VARCHAR(20) NOT NULL DEFAULT 'base'"),
        ('supplement_hash', 'VARCHAR(64) NULL'),
        ('merge_detail', 'JSON NULL'),
    ],
}


def _ensure_columns():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if 'datasets' not in existing_tables:
        return
    present = {c['name'] for c in inspector.get_columns('datasets')}
    with engine.begin() as conn:
        for name, ddl in NEW_COLUMNS['datasets']:
            if name not in present:
                conn.execute(text(f'ALTER TABLE datasets ADD COLUMN {name} {ddl}'))
        if engine.dialect.name == 'mysql' and 'parent_id' not in present:
            conn.execute(text('ALTER TABLE datasets ADD INDEX ix_datasets_parent_id (parent_id)'))
            conn.execute(text('ALTER TABLE datasets ADD CONSTRAINT uq_datasets_supplement UNIQUE (parent_id, supplement_hash)'))
            conn.execute(text('ALTER TABLE datasets ADD CONSTRAINT fk_datasets_parent FOREIGN KEY (parent_id) REFERENCES datasets(id)'))


def migrate():
    Base.metadata.create_all(engine)
    _ensure_columns()


if __name__ == '__main__':
    migrate()
