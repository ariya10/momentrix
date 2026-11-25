"""Store editorial metadata alongside the current clip revision."""

import sqlalchemy as sa
from alembic import op

revision = "0002_clip_metadata"
down_revision = "0001_studio"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("revisions", sa.Column("metadata", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("revisions", "metadata")
