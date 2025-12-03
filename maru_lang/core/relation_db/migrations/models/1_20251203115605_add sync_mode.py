from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "document_group" ADD "sync_mode" SMALLINT NOT NULL DEFAULT 1 /* SERVER: 1\nCLIENT: 2 */;
        ALTER TABLE "document_group" RENAME COLUMN "config_snapshot" TO "rag_components";
        ALTER TABLE "document_group" DROP COLUMN "embedding_model";
        ALTER TABLE "document_group" DROP COLUMN "chunker";
        ALTER TABLE "document_group" DROP COLUMN "loader";
        CREATE INDEX "idx_document_gr_sync_mo_281371" ON "document_group" ("sync_mode");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_document_gr_sync_mo_281371";
        ALTER TABLE "document_group" ADD "embedding_model" VARCHAR(255);
        ALTER TABLE "document_group" RENAME COLUMN "rag_components" TO "config_snapshot";
        ALTER TABLE "document_group" ADD "chunker" VARCHAR(255);
        ALTER TABLE "document_group" ADD "loader" VARCHAR(255);
        ALTER TABLE "document_group" DROP COLUMN "sync_mode";"""


MODELS_STATE = (
    "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"
    "FxDLxRty+wTiTs3Ly/+VMI9R"
)
