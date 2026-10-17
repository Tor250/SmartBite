"""Make recipe preparation time optional for the MVP."""
from alembic import op
import sqlalchemy as sa


revision = "c4b92e6f78ad"
down_revision = "ba258afcaf4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.alter_column("preparation_time_minutes", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("recipes") as batch_op:
        batch_op.alter_column("preparation_time_minutes", existing_type=sa.Integer(), nullable=False)
