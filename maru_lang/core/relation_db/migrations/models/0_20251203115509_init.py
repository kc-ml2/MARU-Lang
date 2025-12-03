from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "document" (
    "id" VARCHAR(64) NOT NULL PRIMARY KEY,
    "name" VARCHAR(255) NOT NULL,
    "file_path" VARCHAR(500),
    "file_size" BIGINT,
    "head_hash" VARCHAR(64),
    "full_hash" VARCHAR(64),
    "source_fingerprint" VARCHAR(64) UNIQUE,
    "metadata" JSON NOT NULL,
    "status" SMALLINT NOT NULL DEFAULT 1 /* PROCESSING: 1\nACTIVE: 2\nINACTIVE: 3 */,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_document_name_c92aaa" ON "document" ("name");
CREATE INDEX IF NOT EXISTS "idx_document_head_ha_32a556" ON "document" ("head_hash");
CREATE INDEX IF NOT EXISTS "idx_document_full_ha_e25e82" ON "document" ("full_hash");
CREATE INDEX IF NOT EXISTS "idx_document_name_8cdafa" ON "document" ("name", "file_size", "head_hash");
CREATE TABLE IF NOT EXISTS "otp" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "email" VARCHAR(255) NOT NULL,
    "code" VARCHAR(6) NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_otp_email_53603b" ON "otp" ("email");
CREATE TABLE IF NOT EXISTS "refresh_token" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "user_id" VARCHAR(255) NOT NULL,
    "device_id" VARCHAR(255) NOT NULL,
    "refresh_token" TEXT NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expires_at" TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_refresh_tok_user_id_8938ab" ON "refresh_token" ("user_id");
CREATE INDEX IF NOT EXISTS "idx_refresh_tok_device__66eb54" ON "refresh_token" ("device_id");
CREATE TABLE IF NOT EXISTS "user_role" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(255) NOT NULL UNIQUE,
    "description" TEXT
);
CREATE INDEX IF NOT EXISTS "idx_user_role_name_772e8c" ON "user_role" ("name");
CREATE TABLE IF NOT EXISTS "user" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(255),
    "email" VARCHAR(255) NOT NULL UNIQUE,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "role_id" INT REFERENCES "user_role" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_user_name_76f409" ON "user" ("name");
CREATE INDEX IF NOT EXISTS "idx_user_email_1b4f1c" ON "user" ("email");
CREATE TABLE IF NOT EXISTS "conversation" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "question" TEXT NOT NULL,
    "enhanced_question" TEXT,
    "answer" TEXT NOT NULL,
    "metadata" JSON NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "user_id" INT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "conversation_reference" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "score" REAL NOT NULL,
    "conversation_id" INT NOT NULL REFERENCES "conversation" ("id") ON DELETE CASCADE,
    "document_id" VARCHAR(64) NOT NULL REFERENCES "document" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "document_group" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(255) NOT NULL UNIQUE,
    "base_path" VARCHAR(500) NOT NULL UNIQUE,
    "description" TEXT,
    "version_id" VARCHAR(64),
    "loader" VARCHAR(255),
    "chunker" VARCHAR(255),
    "embedding_model" VARCHAR(255),
    "config_snapshot" JSON,
    "minhash_signature" JSON,
    "signature_updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "manager_id" INT NOT NULL REFERENCES "user" ("id") ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS "idx_document_gr_version_b0fe5f" ON "document_group" ("version_id");
CREATE TABLE IF NOT EXISTS "document_group_inclusion" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "child_id" INT NOT NULL REFERENCES "document_group" ("id") ON DELETE CASCADE,
    "parent_id" INT NOT NULL REFERENCES "document_group" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_document_gr_parent__07ffc5" UNIQUE ("parent_id", "child_id")
);
CREATE TABLE IF NOT EXISTS "document_group_membership" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "document_id" VARCHAR(64) NOT NULL REFERENCES "document" ("id") ON DELETE CASCADE,
    "group_id" INT NOT NULL REFERENCES "document_group" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "user_group" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "name" VARCHAR(255) NOT NULL UNIQUE,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "manager_id" INT NOT NULL REFERENCES "user" ("id") ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS "group_permission" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "action" SMALLINT NOT NULL /* READ: 1\nWRITE: 2\nMANAGE: 3 */,
    "document_group_id" INT NOT NULL REFERENCES "document_group" ("id") ON DELETE CASCADE,
    "user_group_id" INT NOT NULL REFERENCES "user_group" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_group_permi_user_gr_10e5f4" UNIQUE ("user_group_id", "document_group_id", "action")
);
CREATE TABLE IF NOT EXISTS "user_group_inclusion" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "child_id" INT NOT NULL REFERENCES "user_group" ("id") ON DELETE CASCADE,
    "parent_id" INT NOT NULL REFERENCES "user_group" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "user_group_membership" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "group_id" INT NOT NULL REFERENCES "user_group" ("id") ON DELETE CASCADE,
    "user_id" INT NOT NULL REFERENCES "user" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "user_token" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "user_id" VARCHAR(255) NOT NULL,
    "device_id" VARCHAR(255) NOT NULL,
    "jwt_token" TEXT NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS "idx_user_token_user_id_c889cf" ON "user_token" ("user_id");
CREATE INDEX IF NOT EXISTS "idx_user_token_device__8127d9" ON "user_token" ("device_id");
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
    "6IkU8M2+avGGwj7at1Xz8vI/jPllQQ=="
)
