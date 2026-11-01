"""add evidence_type and per-incident unique content hash to evidence_sources

Revision ID: a3f9c2d71b45
Revises: e86d968218a3
Create Date: 2026-10-31 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f9c2d71b45"
down_revision: str | None = "e86d968218a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "uq_evidence_incident_content_hash"


def upgrade() -> None:
    bind = op.get_bind()

    # Never delete or rewrite existing evidence: fail loudly if duplicates exist.
    duplicates = bind.execute(
        sa.text(
            """
            SELECT incident_id, content_hash, COUNT(*) AS copies
            FROM evidence_sources
            GROUP BY incident_id, content_hash
            HAVING COUNT(*) > 1
            ORDER BY copies DESC
            LIMIT 10
            """
        )
    ).fetchall()
    if duplicates:
        sample = "; ".join(
            f"incident_id={row.incident_id} content_hash={row.content_hash} copies={row.copies}"
            for row in duplicates
        )
        raise RuntimeError(
            f"Cannot add {CONSTRAINT_NAME}: evidence_sources already contains duplicate "
            f"(incident_id, content_hash) pairs (showing up to 10): {sample}. "
            "Resolve these rows manually, then re-run the migration. "
            "No data has been modified."
        )

    # Nullable: legacy/seeded rows keep NULL rather than a guessed type.
    op.add_column(
        "evidence_sources",
        sa.Column("evidence_type", sa.String(length=50), nullable=True),
    )
    op.create_unique_constraint(
        CONSTRAINT_NAME, "evidence_sources", ["incident_id", "content_hash"]
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, "evidence_sources", type_="unique")
    op.drop_column("evidence_sources", "evidence_type")