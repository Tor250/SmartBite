"""Добавляет отзывы и ссылки для обмена рецептами."""
from alembic import op
import sqlalchemy as sa


revision = "8e91c4a0d6f3"
down_revision = "d7c4a1e82b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipes", sa.Column("share_token", sa.String(length=64), nullable=True))
    op.create_index("ix_recipes_share_token", "recipes", ["share_token"], unique=True)
    op.add_column("recipe_ratings", sa.Column("liked", sa.Boolean(), nullable=True))
    op.add_column("recipe_ratings", sa.Column("review", sa.String(length=1000), nullable=True))
    with op.batch_alter_table("recipe_ratings") as batch_op:
        batch_op.alter_column("suitable", existing_type=sa.Boolean(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE recipe_ratings SET suitable = 0 WHERE suitable IS NULL")
    with op.batch_alter_table("recipe_ratings") as batch_op:
        batch_op.alter_column("suitable", existing_type=sa.Boolean(), nullable=False)
        batch_op.drop_column("review")
        batch_op.drop_column("liked")
    op.drop_index("ix_recipes_share_token", table_name="recipes")
    op.drop_column("recipes", "share_token")
