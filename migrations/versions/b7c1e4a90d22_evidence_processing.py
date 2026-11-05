"""evidence processing jobs, parsed records and the single-worker lease

Revision ID: b7c1e4a90d22
Revises: a3f9c2d71b45
Create Date: 2026-11-04 00:00:00.000000

Additive only: no existing table is rewritten or dropped, and legacy
``evidence_sources.parse_status = 'not_required'`` rows are preserved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c1e4a90d22"
down_revision: str | None = "a3f9c2d71b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "evidence_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("completed_content_hash", sa.String(length=64), nullable=True),
        sa.Column("completed_parser_version", sa.String(length=50), nullable=True),
        sa.Column("records_parsed", sa.Integer(), nullable=False),
        sa.Column("processing_duration_ms", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ("
            "'queued', 'validating', 'extracting', 'parsing', "
            "'normalizing', 'parsed', 'failed'"
            ")",
            name="ck_evidence_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_evidence_jobs_attempts"),
        sa.CheckConstraint("records_parsed >= 0", name="ck_evidence_jobs_records"),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_sources.id"],
            name="fk_evidence_jobs_evidence_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_evidence_jobs_incident_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evidence_id", name="uq_evidence_jobs_evidence_id"),
    )
    op.create_index("ix_evidence_jobs_evidence_id", "evidence_jobs", ["evidence_id"])
    op.create_index("ix_evidence_jobs_incident_id", "evidence_jobs", ["incident_id"])
    op.create_index(
        "ix_evidence_jobs_status_type",
        "evidence_jobs",
        ["status", "evidence_type", "created_at"],
    )

    op.create_table(
        "parsed_evidence_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("record_id", sa.String(length=64), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("record_type", sa.String(length=50), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("timestamp_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timestamp_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", JSON_TYPE, nullable=False),
        sa.Column("source", JSON_TYPE, nullable=False),
        sa.Column("parser_name", sa.String(length=50), nullable=False),
        sa.Column("parser_version", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("record_index >= 0", name="ck_parsed_record_index"),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_sources.id"],
            name="fk_parsed_records_evidence_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_parsed_records_incident_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_id", "record_index", name="uq_parsed_record_position"
        ),
    )
    op.create_index(
        "ix_parsed_records_evidence_order",
        "parsed_evidence_records",
        ["evidence_id", "record_index"],
    )
    op.create_index(
        "ix_parsed_records_evidence_id", "parsed_evidence_records", ["evidence_id"]
    )
    op.create_index(
        "ix_parsed_records_incident_id", "parsed_evidence_records", ["incident_id"]
    )

    op.create_table(
        "worker_lease",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_worker_lease_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("worker_lease")

    op.drop_index("ix_parsed_records_incident_id", table_name="parsed_evidence_records")
    op.drop_index("ix_parsed_records_evidence_id", table_name="parsed_evidence_records")
    op.drop_index("ix_parsed_records_evidence_order", table_name="parsed_evidence_records")
    op.drop_table("parsed_evidence_records")

    op.drop_index("ix_evidence_jobs_status_type", table_name="evidence_jobs")
    op.drop_index("ix_evidence_jobs_incident_id", table_name="evidence_jobs")
    op.drop_index("ix_evidence_jobs_evidence_id", table_name="evidence_jobs")
    op.drop_table("evidence_jobs")
