from collections.abc import Generator
import time

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _database_url() -> str | URL:
    if settings.db_host and settings.db_name and settings.db_user:
        query = {}
        if settings.db_sslmode:
            query["sslmode"] = settings.db_sslmode

        return URL.create(
            "postgresql+psycopg",
            username=settings.db_user,
            password=settings.db_password,
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            query=query,
        )

    if settings.database_url.startswith("postgresql://"):
        return settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    return settings.database_url


engine = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SCHEMA_LOCK_TIMEOUT = "10s"
SCHEMA_STATEMENT_TIMEOUT = "45s"


def _set_schema_timeouts(connection) -> None:
    if engine.dialect.name != "postgresql":
        return
    connection.execute(text(f"SET LOCAL lock_timeout = '{SCHEMA_LOCK_TIMEOUT}'"))
    connection.execute(text(f"SET LOCAL statement_timeout = '{SCHEMA_STATEMENT_TIMEOUT}'"))


def _run_schema_statement(statement: str) -> None:
    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        connection.execute(text(statement))


def _run_schema_operation(operation) -> None:
    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        operation(connection)


def init_db() -> None:
    from backend import models  # noqa: F401

    _wait_for_database()
    Base.metadata.create_all(bind=engine)
    _ensure_tag_tables()
    _ensure_crm_funnel_tables()
    _ensure_whatsapp_crm_tables()
    _ensure_crm_lead_columns()
    _ensure_whatsapp_ai_settings_columns()
    _ensure_whatsapp_campaign_columns()
    _ensure_whatsapp_send_columns()
    _ensure_whatsapp_conversation_columns()
    _ensure_search_run_columns()
    _ensure_lead_columns()
    _ensure_lead_list_columns()
    _ensure_email_template_columns()
    _ensure_email_campaign_columns()
    _ensure_email_send_columns()


def _ensure_whatsapp_crm_tables() -> None:
    from backend.models import (
        CrmLead,
        CrmFunnel,
        CrmFunnelStage,
        CrmStageHistory,
        WhatsAppAiSettings,
        WhatsAppCampaign,
        WhatsAppCampaignTemplate,
        WhatsAppConversation,
        WhatsAppInstance,
        WhatsAppMessage,
        WhatsAppMessageTemplate,
        WhatsAppPortfolioItem,
        WhatsAppWebhookSettings,
        WhatsAppSend,
    )

    Base.metadata.create_all(
        bind=engine,
        tables=[
            WhatsAppInstance.__table__,
            WhatsAppMessageTemplate.__table__,
            WhatsAppCampaign.__table__,
            WhatsAppCampaignTemplate.__table__,
            WhatsAppSend.__table__,
            WhatsAppConversation.__table__,
            WhatsAppMessage.__table__,
            WhatsAppAiSettings.__table__,
            WhatsAppPortfolioItem.__table__,
            WhatsAppWebhookSettings.__table__,
            CrmFunnel.__table__,
            CrmFunnelStage.__table__,
            CrmLead.__table__,
            CrmStageHistory.__table__,
        ],
    )


def _ensure_tag_tables() -> None:
    from backend.models import LeadTag, Tag

    Base.metadata.create_all(bind=engine, tables=[Tag.__table__, LeadTag.__table__])

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "tags" not in table_names:
        return

    lead_tag_columns = {column["name"]: column for column in inspector.get_columns("lead_tags")} if "lead_tags" in table_names else {}

    _run_schema_statement("CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_lower_name ON tags (lower(name))")

    if "lead_tags" not in table_names:
        return

    origin_column = lead_tag_columns.get("origin")
    if origin_column is None:
        _run_schema_statement("ALTER TABLE lead_tags ADD COLUMN origin VARCHAR(20) NOT NULL DEFAULT 'manual'")
    else:
        _run_schema_statement("UPDATE lead_tags SET origin = 'manual' WHERE origin IS NULL OR origin = ''")

    if origin_column is not None and engine.dialect.name == "postgresql":
        _run_schema_statement("ALTER TABLE lead_tags ALTER COLUMN origin SET DEFAULT 'manual'")
        if origin_column.get("nullable", True):
            _run_schema_statement("ALTER TABLE lead_tags ALTER COLUMN origin SET NOT NULL")

    if engine.dialect.name == "postgresql":
        _run_schema_operation(
            lambda connection: _ensure_pg_constraint(
                connection,
                "lead_tags",
                "ck_lead_tags_origin",
                "CHECK (origin IN ('manual', 'ai'))",
            )
        )


DEFAULT_CRM_FUNNEL_NAME = "Funil padrão"
DEFAULT_CRM_STAGES = [
    {
        "key": "new",
        "label": "Novo",
        "color": "#f3f4f6",
        "description": "Lead recém-chegado, ainda sem resposta ou qualificação.",
        "position": 0,
        "is_won": False,
        "is_lost": False,
    },
    {
        "key": "responded",
        "label": "Respondeu",
        "color": "#dff7f1",
        "description": "Lead respondeu à abordagem, mas ainda não há qualificação suficiente.",
        "position": 1,
        "is_won": False,
        "is_lost": False,
    },
    {
        "key": "qualified",
        "label": "Qualificado",
        "color": "#dcf6e8",
        "description": "Lead demonstrou dor, necessidade ou encaixe claro com a oferta.",
        "position": 2,
        "is_won": False,
        "is_lost": False,
    },
    {
        "key": "not_interested",
        "label": "Sem interesse",
        "color": "#ffe4e6",
        "description": "Lead recusou a conversa, pediu para não seguir ou demonstrou desinteresse claro.",
        "position": 3,
        "is_won": False,
        "is_lost": True,
    },
    {
        "key": "converted",
        "label": "Convertido",
        "color": "#fff4ce",
        "description": "Lead aceitou avançar para reunião, fechamento ou próximo passo comercial concreto.",
        "position": 4,
        "is_won": True,
        "is_lost": False,
    },
]


def _ensure_crm_funnel_tables() -> None:
    from backend.models import CrmFunnel, CrmFunnelStage

    Base.metadata.create_all(bind=engine, tables=[CrmFunnel.__table__, CrmFunnelStage.__table__])

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "crm_funnels" not in table_names or "crm_funnel_stages" not in table_names:
        return
    stage_columns = {column["name"] for column in inspector.get_columns("crm_funnel_stages")}
    if "description" not in stage_columns:
        _run_schema_statement("ALTER TABLE crm_funnel_stages ADD COLUMN description VARCHAR(500)")

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_funnels_lower_name ON crm_funnels (lower(name))"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_funnel_stages_funnel_key "
                "ON crm_funnel_stages (funnel_id, key)"
            )
        )
        default_funnel_id = _ensure_default_crm_funnel(connection)
        _ensure_default_crm_funnel_stages(connection, default_funnel_id)
        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_funnels_single_default "
                    "ON crm_funnels (is_default) WHERE is_default = true"
                )
            )


def _ensure_default_crm_funnel(connection) -> int:
    rows = list(connection.execute(text("SELECT id FROM crm_funnels WHERE is_default = :is_default ORDER BY id"), {"is_default": True}))
    if rows:
        default_id = int(rows[0][0])
        for row in rows[1:]:
            connection.execute(text("UPDATE crm_funnels SET is_default = :is_default WHERE id = :id"), {"is_default": False, "id": row[0]})
        return default_id

    existing = connection.execute(
        text("SELECT id FROM crm_funnels WHERE lower(name) = lower(:name) ORDER BY id LIMIT 1"),
        {"name": DEFAULT_CRM_FUNNEL_NAME},
    ).first()
    if existing:
        default_id = int(existing[0])
        connection.execute(text("UPDATE crm_funnels SET is_default = :is_default WHERE id = :id"), {"is_default": True, "id": default_id})
        return default_id

    inserted_id = connection.execute(
        text("INSERT INTO crm_funnels (name, description, is_default) VALUES (:name, :description, :is_default) RETURNING id"),
        {"name": DEFAULT_CRM_FUNNEL_NAME, "description": "Funil padrão migrado dos estágios originais.", "is_default": True},
    ).scalar_one()
    return int(inserted_id)


def _ensure_default_crm_funnel_stages(connection, funnel_id: int) -> None:
    for stage in DEFAULT_CRM_STAGES:
        existing = connection.execute(
            text("SELECT id FROM crm_funnel_stages WHERE funnel_id = :funnel_id AND key = :key"),
            {"funnel_id": funnel_id, "key": stage["key"]},
        ).first()
        params = {**stage, "funnel_id": funnel_id}
        if existing:
            connection.execute(
                text(
                    "UPDATE crm_funnel_stages "
                    "SET label = :label, color = :color, description = :description, "
                    "position = :position, is_won = :is_won, is_lost = :is_lost "
                    "WHERE id = :id"
                ),
                {**params, "id": existing[0]},
            )
            continue
        connection.execute(
            text(
                "INSERT INTO crm_funnel_stages "
                "(funnel_id, key, label, color, description, position, is_won, is_lost) "
                "VALUES (:funnel_id, :key, :label, :color, :description, :position, :is_won, :is_lost)"
            ),
            params,
        )


def _ensure_crm_lead_columns() -> None:
    _ensure_crm_funnel_tables()

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "crm_leads" not in table_names:
        return

    original_columns = {column["name"] for column in inspector.get_columns("crm_leads")}
    original_position_missing = "position" not in original_columns
    if engine.dialect.name == "sqlite" and _sqlite_crm_leads_needs_rebuild(inspector):
        _rebuild_sqlite_crm_tables()
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    existing_columns = {column["name"] for column in inspector.get_columns("crm_leads")}
    history_table_exists = "crm_stage_history" in table_names
    history_columns = {column["name"] for column in inspector.get_columns("crm_stage_history")} if history_table_exists else set()
    position_column_missing = "position" not in existing_columns
    should_reset_positions = original_position_missing or position_column_missing
    funnel_id_missing = "funnel_id" not in existing_columns
    stage_id_missing = "stage_id" not in existing_columns

    if engine.dialect.name == "postgresql":
        def drop_legacy_constraints(connection) -> None:
            _drop_pg_check_constraints_for_columns(connection, "crm_leads", ["stage"])
            if history_table_exists:
                _drop_pg_check_constraints_for_columns(connection, "crm_stage_history", ["from_stage", "to_stage"])
            _drop_pg_unique_lead_id_constraints(connection)
            _drop_pg_unique_lead_id_indexes(connection)

        _run_schema_operation(drop_legacy_constraints)
        _run_schema_statement("ALTER TABLE crm_leads ALTER COLUMN stage TYPE VARCHAR(60)")
        if history_table_exists and "from_stage" in history_columns:
            _run_schema_statement("ALTER TABLE crm_stage_history ALTER COLUMN from_stage TYPE VARCHAR(60)")
        if history_table_exists and "to_stage" in history_columns:
            _run_schema_statement("ALTER TABLE crm_stage_history ALTER COLUMN to_stage TYPE VARCHAR(60)")

    if position_column_missing:
        _run_schema_statement("ALTER TABLE crm_leads ADD COLUMN position INTEGER")
    if funnel_id_missing:
        _run_schema_statement("ALTER TABLE crm_leads ADD COLUMN funnel_id INTEGER")
    if stage_id_missing:
        _run_schema_statement("ALTER TABLE crm_leads ADD COLUMN stage_id INTEGER")
    if history_table_exists and "from_stage_id" not in history_columns:
        _run_schema_statement("ALTER TABLE crm_stage_history ADD COLUMN from_stage_id INTEGER")
    if history_table_exists and "to_stage_id" not in history_columns:
        _run_schema_statement("ALTER TABLE crm_stage_history ADD COLUMN to_stage_id INTEGER")

    if engine.dialect.name == "postgresql":
        def ensure_crm_foreign_keys(connection) -> None:
            _ensure_pg_constraint(
                connection,
                "crm_leads",
                "fk_crm_leads_funnel_id",
                "FOREIGN KEY (funnel_id) REFERENCES crm_funnels(id) ON DELETE RESTRICT",
            )
            _ensure_pg_constraint(
                connection,
                "crm_leads",
                "fk_crm_leads_stage_id",
                "FOREIGN KEY (stage_id) REFERENCES crm_funnel_stages(id) ON DELETE RESTRICT",
            )
            if history_table_exists:
                _ensure_pg_constraint(
                    connection,
                    "crm_stage_history",
                    "fk_crm_stage_history_from_stage_id",
                    "FOREIGN KEY (from_stage_id) REFERENCES crm_funnel_stages(id) ON DELETE SET NULL",
                )
                _ensure_pg_constraint(
                    connection,
                    "crm_stage_history",
                    "fk_crm_stage_history_to_stage_id",
                    "FOREIGN KEY (to_stage_id) REFERENCES crm_funnel_stages(id) ON DELETE SET NULL",
                )

        _run_schema_operation(ensure_crm_foreign_keys)

    def backfill_crm_cards(connection) -> None:
        _backfill_crm_lead_funnels(connection)
        _backfill_crm_lead_positions(connection, reset=should_reset_positions)
        _backfill_crm_stage_history_stage_ids(connection)

    _run_schema_operation(backfill_crm_cards)
    _run_schema_statement(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_leads_lead_funnel "
        "ON crm_leads (lead_id, funnel_id)"
    )
    if engine.dialect.name == "postgresql":
        _run_schema_statement("ALTER TABLE crm_leads ALTER COLUMN funnel_id SET NOT NULL")
        _run_schema_statement("ALTER TABLE crm_leads ALTER COLUMN stage_id SET NOT NULL")


def _quote_pg_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _drop_pg_check_constraints_for_columns(connection, table_name: str, column_names: list[str]) -> None:
    patterns = {f"pattern_{index}": f"%{column_name}%" for index, column_name in enumerate(column_names)}
    clauses = " OR ".join(f"pg_get_constraintdef(con.oid) ILIKE :pattern_{index}" for index in range(len(column_names)))
    rows = connection.execute(
        text(
            f"""
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = current_schema()
              AND rel.relname = :table_name
              AND con.contype = 'c'
              AND ({clauses})
            """
        ),
        {"table_name": table_name, **patterns},
    )
    for row in rows:
        connection.execute(
            text(
                f"ALTER TABLE {_quote_pg_identifier(table_name)} "
                f"DROP CONSTRAINT IF EXISTS {_quote_pg_identifier(str(row.conname))}"
            )
        )


def _drop_pg_unique_lead_id_constraints(connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN unnest(con.conkey) AS cols(attnum) ON true
            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = cols.attnum
            WHERE nsp.nspname = current_schema()
              AND rel.relname = 'crm_leads'
              AND con.contype = 'u'
              AND array_length(con.conkey, 1) = 1
              AND att.attname = 'lead_id'
            """
        )
    )
    for row in rows:
        connection.execute(
            text(
                f"ALTER TABLE {_quote_pg_identifier('crm_leads')} "
                f"DROP CONSTRAINT IF EXISTS {_quote_pg_identifier(str(row.conname))}"
            )
        )


def _drop_pg_unique_lead_id_indexes(connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT nsp.nspname AS schema_name, idx.relname AS index_name
            FROM pg_index ind
            JOIN pg_class idx ON idx.oid = ind.indexrelid
            JOIN pg_class rel ON rel.oid = ind.indrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN unnest(ind.indkey) AS cols(attnum) ON true
            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = cols.attnum
            WHERE nsp.nspname = current_schema()
              AND rel.relname = 'crm_leads'
              AND ind.indisunique = true
              AND ind.indisprimary = false
              AND ind.indnatts = 1
              AND att.attname = 'lead_id'
              AND NOT EXISTS (
                SELECT 1
                FROM pg_constraint con
                WHERE con.conindid = idx.oid
              )
            """
        )
    )
    for row in rows:
        connection.execute(
            text(
                "DROP INDEX IF EXISTS "
                f"{_quote_pg_identifier(str(row.schema_name))}.{_quote_pg_identifier(str(row.index_name))}"
            )
        )


def _ensure_pg_constraint(connection, table_name: str, constraint_name: str, definition: str) -> None:
    connection.execute(
        text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = '{constraint_name}'
                      AND conrelid = '{table_name}'::regclass
                ) THEN
                    ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} {definition};
                END IF;
            END $$;
            """
        )
    )


def _backfill_crm_lead_funnels(connection) -> None:
    default_funnel_id = _ensure_default_crm_funnel(connection)
    _ensure_default_crm_funnel_stages(connection, default_funnel_id)
    default_stage_id = connection.execute(
        text(
            "SELECT id FROM crm_funnel_stages "
            "WHERE funnel_id = :funnel_id AND key = 'new' "
            "ORDER BY position LIMIT 1"
        ),
        {"funnel_id": default_funnel_id},
    ).scalar()

    connection.execute(
        text("UPDATE crm_leads SET funnel_id = :funnel_id WHERE funnel_id IS NULL"),
        {"funnel_id": default_funnel_id},
    )
    connection.execute(
        text(
            """
            UPDATE crm_leads
            SET stage_id = (
                SELECT crm_funnel_stages.id
                FROM crm_funnel_stages
                WHERE crm_funnel_stages.funnel_id = crm_leads.funnel_id
                  AND crm_funnel_stages.key = crm_leads.stage
                LIMIT 1
            )
            WHERE stage_id IS NULL
            """
        )
    )
    if default_stage_id is not None:
        connection.execute(
            text("UPDATE crm_leads SET stage_id = :stage_id WHERE stage_id IS NULL"),
            {"stage_id": default_stage_id},
        )
    connection.execute(
        text(
            """
            UPDATE crm_leads
            SET stage = (
                SELECT crm_funnel_stages.key
                FROM crm_funnel_stages
                WHERE crm_funnel_stages.id = crm_leads.stage_id
                LIMIT 1
            )
            WHERE stage_id IS NOT NULL
              AND stage != (
                SELECT crm_funnel_stages.key
                FROM crm_funnel_stages
                WHERE crm_funnel_stages.id = crm_leads.stage_id
                LIMIT 1
              )
            """
        )
    )


def _backfill_crm_stage_history_stage_ids(connection) -> None:
    table_names = inspect(connection).get_table_names()
    if "crm_stage_history" not in table_names:
        return

    default_funnel_id = _ensure_default_crm_funnel(connection)
    connection.execute(
        text(
            """
            UPDATE crm_stage_history
            SET from_stage_id = (
                SELECT crm_funnel_stages.id
                FROM crm_funnel_stages
                WHERE crm_funnel_stages.funnel_id = :funnel_id
                  AND crm_funnel_stages.key = crm_stage_history.from_stage
                LIMIT 1
            )
            WHERE from_stage_id IS NULL
            """
        ),
        {"funnel_id": default_funnel_id},
    )
    connection.execute(
        text(
            """
            UPDATE crm_stage_history
            SET to_stage_id = (
                SELECT crm_funnel_stages.id
                FROM crm_funnel_stages
                WHERE crm_funnel_stages.funnel_id = :funnel_id
                  AND crm_funnel_stages.key = crm_stage_history.to_stage
                LIMIT 1
            )
            WHERE to_stage_id IS NULL
            """
        ),
        {"funnel_id": default_funnel_id},
    )


def _sqlite_crm_leads_needs_rebuild(inspector) -> bool:
    columns = {column["name"] for column in inspector.get_columns("crm_leads")}
    if not {"funnel_id", "stage_id", "position"}.issubset(columns):
        return True

    for constraint in inspector.get_unique_constraints("crm_leads"):
        if constraint.get("column_names") == ["lead_id"]:
            return True
    for constraint in inspector.get_check_constraints("crm_leads"):
        if constraint.get("name") == "ck_crm_leads_stage":
            return True
    return False


def _rebuild_sqlite_crm_tables() -> None:
    with engine.begin() as connection:
        _ensure_default_crm_funnel(connection)
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        crm_columns = {column["name"] for column in inspect(connection).get_columns("crm_leads")}
        selected_columns = [
            "id",
            "lead_id",
            "stage",
            "qualification_notes",
            "score",
            "position" if "position" in crm_columns else "NULL AS position",
            "updated_at",
            "funnel_id" if "funnel_id" in crm_columns else "NULL AS funnel_id",
            "stage_id" if "stage_id" in crm_columns else "NULL AS stage_id",
        ]
        connection.execute(
            text(
                """
                CREATE TABLE crm_leads_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    lead_id INTEGER NOT NULL,
                    funnel_id INTEGER,
                    stage_id INTEGER,
                    stage VARCHAR(60) NOT NULL,
                    qualification_notes TEXT,
                    score INTEGER,
                    position INTEGER,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO crm_leads_new "
                "(id, lead_id, stage, qualification_notes, score, position, updated_at, funnel_id, stage_id) "
                f"SELECT {', '.join(selected_columns)} FROM crm_leads"
            )
        )
        connection.execute(text("DROP TABLE crm_leads"))
        connection.execute(text("ALTER TABLE crm_leads_new RENAME TO crm_leads"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crm_leads_id ON crm_leads (id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crm_leads_funnel_id ON crm_leads (funnel_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crm_leads_stage_id ON crm_leads (stage_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_leads_lead_funnel ON crm_leads (lead_id, funnel_id)"))
        _rebuild_sqlite_crm_stage_history(connection)
        connection.execute(text("PRAGMA foreign_keys=ON"))


def _rebuild_sqlite_crm_stage_history(connection) -> None:
    if "crm_stage_history" not in inspect(connection).get_table_names():
        return
    columns = {column["name"] for column in inspect(connection).get_columns("crm_stage_history")}
    selected_columns = [
        "id",
        "crm_lead_id",
        "from_stage",
        "to_stage",
        "changed_at",
        "changed_by",
        "from_stage_id" if "from_stage_id" in columns else "NULL AS from_stage_id",
        "to_stage_id" if "to_stage_id" in columns else "NULL AS to_stage_id",
    ]
    connection.execute(
        text(
            """
            CREATE TABLE crm_stage_history_new (
                id INTEGER NOT NULL PRIMARY KEY,
                crm_lead_id INTEGER NOT NULL,
                from_stage VARCHAR(60) NOT NULL,
                to_stage VARCHAR(60) NOT NULL,
                changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                changed_by VARCHAR(20) NOT NULL,
                from_stage_id INTEGER,
                to_stage_id INTEGER,
                CONSTRAINT ck_crm_stage_history_changed_by CHECK (changed_by IN ('ai', 'manual'))
            )
            """
        )
    )
    connection.execute(
        text(
            "INSERT INTO crm_stage_history_new "
            "(id, crm_lead_id, from_stage, to_stage, changed_at, changed_by, from_stage_id, to_stage_id) "
            f"SELECT {', '.join(selected_columns)} FROM crm_stage_history"
        )
    )
    connection.execute(text("DROP TABLE crm_stage_history"))
    connection.execute(text("ALTER TABLE crm_stage_history_new RENAME TO crm_stage_history"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crm_stage_history_id ON crm_stage_history (id)"))


def _backfill_crm_lead_positions(connection, *, reset: bool = False) -> None:
    if reset:
        rows = connection.execute(
            text(
                "SELECT id, funnel_id, stage_id, stage FROM crm_leads "
                "ORDER BY funnel_id ASC, stage_id ASC, stage ASC, updated_at DESC, id DESC"
            )
        ).mappings()
        positions_by_stage: dict[tuple[int | None, int | None, str], int] = {}
        for row in rows:
            stage_key = (row["funnel_id"], row["stage_id"], str(row["stage"]))
            position = positions_by_stage.get(stage_key, 0)
            connection.execute(
                text("UPDATE crm_leads SET position = :position WHERE id = :id"),
                {"position": position, "id": row["id"]},
            )
            positions_by_stage[stage_key] = position + 1
        return

    stages = connection.execute(
        text("SELECT DISTINCT funnel_id, stage_id, stage FROM crm_leads WHERE position IS NULL")
    ).mappings()
    for stage_row in stages:
        max_position = connection.execute(
            text(
                "SELECT MAX(position) FROM crm_leads "
                "WHERE funnel_id = :funnel_id AND stage_id = :stage_id AND stage = :stage AND position IS NOT NULL"
            ),
            {
                "funnel_id": stage_row["funnel_id"],
                "stage_id": stage_row["stage_id"],
                "stage": stage_row["stage"],
            },
        ).scalar()
        next_position = int(max_position) + 1 if max_position is not None else 0
        rows = connection.execute(
            text(
                "SELECT id FROM crm_leads "
                "WHERE funnel_id = :funnel_id AND stage_id = :stage_id AND stage = :stage AND position IS NULL "
                "ORDER BY updated_at DESC, id DESC"
            ),
            {
                "funnel_id": stage_row["funnel_id"],
                "stage_id": stage_row["stage_id"],
                "stage": stage_row["stage"],
            },
        ).mappings()
        for row in rows:
            connection.execute(
                text("UPDATE crm_leads SET position = :position WHERE id = :id"),
                {"position": next_position, "id": row["id"]},
            )
            next_position += 1


def _ensure_whatsapp_conversation_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_conversations" not in inspector.get_table_names():
        return

    lead_id_column = next(
        (column for column in inspector.get_columns("whatsapp_conversations") if column["name"] == "lead_id"),
        None,
    )
    if not lead_id_column or lead_id_column.get("nullable", True):
        return

    try:
        with engine.begin() as connection:
            _set_schema_timeouts(connection)
            connection.execute(text("ALTER TABLE whatsapp_conversations ALTER COLUMN lead_id DROP NOT NULL"))
    except SQLAlchemyError:
        return


def _ensure_whatsapp_ai_settings_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_ai_settings" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("whatsapp_ai_settings")}
    migrations = {
        "services_description": (
            "ALTER TABLE whatsapp_ai_settings "
            "ADD COLUMN services_description TEXT NOT NULL DEFAULT ''"
        ),
        "auto_apply_tags_enabled": (
            "ALTER TABLE whatsapp_ai_settings "
            "ADD COLUMN auto_apply_tags_enabled BOOLEAN NOT NULL DEFAULT FALSE"
        ),
    }
    missing_migrations = {
        column_name: statement
        for column_name, statement in migrations.items()
        if column_name not in existing_columns
    }
    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for statement in missing_migrations.values():
            connection.execute(text(statement))


def _ensure_whatsapp_campaign_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_campaigns" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("whatsapp_campaigns")}
    migrations = {
        "objective": "ALTER TABLE whatsapp_campaigns ADD COLUMN objective TEXT NOT NULL DEFAULT ''",
        "message_mode": "ALTER TABLE whatsapp_campaigns ADD COLUMN message_mode VARCHAR(30) NOT NULL DEFAULT 'template'",
        "language": "ALTER TABLE whatsapp_campaigns ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'pt'",
        "funnel_id": "ALTER TABLE whatsapp_campaigns ADD COLUMN funnel_id INTEGER",
    }
    missing_migrations = {
        column_name: statement
        for column_name, statement in migrations.items()
        if column_name not in existing_columns
    }
    should_ensure_funnel_fk = engine.dialect.name == "postgresql" and (
        "funnel_id" in existing_columns or "funnel_id" in missing_migrations
    )
    if not missing_migrations and not should_ensure_funnel_fk:
        return

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for statement in missing_migrations.values():
            connection.execute(text(statement))
        if should_ensure_funnel_fk:
            _ensure_pg_constraint(
                connection,
                "whatsapp_campaigns",
                "fk_whatsapp_campaigns_funnel_id",
                "FOREIGN KEY (funnel_id) REFERENCES crm_funnels(id) ON DELETE SET NULL",
            )


def _ensure_whatsapp_send_columns() -> None:
    inspector = inspect(engine)
    if "whatsapp_sends" not in inspector.get_table_names():
        return

    columns = inspector.get_columns("whatsapp_sends")
    existing_columns = {column["name"] for column in columns}
    migrations = {
        "generated_content": "ALTER TABLE whatsapp_sends ADD COLUMN generated_content TEXT",
    }
    missing_migrations = {
        column_name: statement
        for column_name, statement in migrations.items()
        if column_name not in existing_columns
    }

    template_id_column = next((column for column in columns if column["name"] == "template_id"), None)
    should_drop_template_not_null = bool(template_id_column and not template_id_column.get("nullable", True))

    if not missing_migrations and not should_drop_template_not_null:
        return

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for statement in missing_migrations.values():
            connection.execute(text(statement))
        if should_drop_template_not_null and engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE whatsapp_sends ALTER COLUMN template_id DROP NOT NULL"))


def _wait_for_database(max_attempts: int = 30, delay_seconds: int = 2) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt == max_attempts:
                raise
            time.sleep(delay_seconds)


def _ensure_email_template_columns() -> None:
    inspector = inspect(engine)
    if "email_templates" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_templates")}
    migrations = {
        "logo_url": "ALTER TABLE email_templates ADD COLUMN logo_url VARCHAR(1000) NOT NULL DEFAULT ''",
        "primary_color": "ALTER TABLE email_templates ADD COLUMN primary_color VARCHAR(20) NOT NULL DEFAULT '#0a0a0a'",
        "text_color": "ALTER TABLE email_templates ADD COLUMN text_color VARCHAR(20) NOT NULL DEFAULT '#333333'",
        "background_color": "ALTER TABLE email_templates ADD COLUMN background_color VARCHAR(20) NOT NULL DEFAULT '#f4f4f4'",
        "content_button_text": (
            "ALTER TABLE email_templates ADD COLUMN content_button_text VARCHAR(200) "
            "NOT NULL DEFAULT 'Open the content'"
        ),
        "contact_mailto_subject": (
            "ALTER TABLE email_templates ADD COLUMN contact_mailto_subject VARCHAR(300) "
            "NOT NULL DEFAULT 'Automation and integration help'"
        ),
        "contact_mailto_body": (
            "ALTER TABLE email_templates ADD COLUMN contact_mailto_body TEXT "
            "NOT NULL DEFAULT 'Hi Cleiton, I saw your email about automation for {{company_name}} "
            "and would like to learn more.'"
        ),
    }

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_search_run_columns() -> None:
    inspector = inspect(engine)
    if "search_runs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("search_runs")}
    migrations = {
        "skip_without_website": "ALTER TABLE search_runs ADD COLUMN skip_without_website BOOLEAN NOT NULL DEFAULT TRUE",
        "only_without_website": "ALTER TABLE search_runs ADD COLUMN only_without_website BOOLEAN NOT NULL DEFAULT FALSE",
        "validate_whatsapp": "ALTER TABLE search_runs ADD COLUMN validate_whatsapp BOOLEAN NOT NULL DEFAULT FALSE",
        "enrich_site_insights": "ALTER TABLE search_runs ADD COLUMN enrich_site_insights BOOLEAN NOT NULL DEFAULT FALSE",
    }

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_lead_columns() -> None:
    inspector = inspect(engine)
    if "leads" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("leads")}
    website_column = next((column for column in inspector.get_columns("leads") if column["name"] == "website"), None)
    should_drop_website_not_null = bool(website_column and not website_column.get("nullable", True))

    try:
        with engine.begin() as connection:
            _set_schema_timeouts(connection)
            if "whatsapp_validated" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN whatsapp_validated BOOLEAN"))
                connection.execute(
                    text(
                        "UPDATE leads "
                        "SET whatsapp_validated = TRUE "
                        "FROM search_runs "
                        "WHERE leads.run_id = search_runs.id "
                        "AND search_runs.validate_whatsapp = TRUE "
                        "AND leads.whatsapp_validated IS NULL"
                    )
                )
            if "whatsapp_validated_at" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_validated_at TIMESTAMP WITH TIME ZONE"))
            if "whatsapp_validation_status" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_validation_status VARCHAR(30)"))
            if "whatsapp_validation_reason" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_validation_reason VARCHAR(80)"))
            connection.execute(
                text(
                    "UPDATE leads "
                    "SET whatsapp_validation_status = 'valid', "
                    "whatsapp_validated_at = COALESCE(whatsapp_validated_at, created_at) "
                    "WHERE whatsapp_validated = TRUE "
                    "AND (whatsapp_validation_status IS NULL OR whatsapp_validated_at IS NULL)"
                )
            )
            if "site_insights" not in existing_columns:
                connection.execute(text("ALTER TABLE leads ADD COLUMN site_insights TEXT"))

            if should_drop_website_not_null:
                connection.execute(text("ALTER TABLE leads ALTER COLUMN website DROP NOT NULL"))
    except SQLAlchemyError:
        return


def _ensure_lead_list_columns() -> None:
    inspector = inspect(engine)
    if "lead_lists" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("lead_lists")}
    migrations = {
        "only_whatsapp_validated": (
            "ALTER TABLE lead_lists ADD COLUMN only_whatsapp_validated BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "only_email_opened": (
            "ALTER TABLE lead_lists ADD COLUMN only_email_opened BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "only_email_clicked": (
            "ALTER TABLE lead_lists ADD COLUMN only_email_clicked BOOLEAN NOT NULL DEFAULT FALSE"
        ),
        "email_engagement_filter_mode": (
            "ALTER TABLE lead_lists ADD COLUMN email_engagement_filter_mode VARCHAR(10) NOT NULL DEFAULT 'or'"
        ),
        "channel": (
            "ALTER TABLE lead_lists ADD COLUMN channel VARCHAR(10) NOT NULL DEFAULT 'both'"
        ),
    }

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_email_campaign_columns() -> None:
    inspector = inspect(engine)
    if "email_campaigns" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_campaigns")}
    migrations = {
        "timezone_name": "ALTER TABLE email_campaigns ADD COLUMN timezone_name VARCHAR(80) NOT NULL DEFAULT 'America/New_York'",
        "objective": "ALTER TABLE email_campaigns ADD COLUMN objective TEXT NOT NULL DEFAULT ''",
        "message_mode": "ALTER TABLE email_campaigns ADD COLUMN message_mode VARCHAR(30) NOT NULL DEFAULT 'template'",
        "language": "ALTER TABLE email_campaigns ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'pt'",
    }

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_email_send_columns() -> None:
    inspector = inspect(engine)
    if "email_sends" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("email_sends")}
    migrations = {
        "generated_content": "ALTER TABLE email_sends ADD COLUMN generated_content TEXT",
    }

    with engine.begin() as connection:
        _set_schema_timeouts(connection)
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
