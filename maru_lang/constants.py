"""Project-wide constants."""

# --- Ingest ---

SUPPORTED_EXTENSIONS = {
    # Documents
    ".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls",
    # Data
    ".csv", ".tsv", ".json",
    # Web/Markup
    ".html", ".htm", ".xml", ".yaml", ".yml",
    # Text/Markdown
    ".md", ".markdown", ".txt", ".text", ".log",
    # Code
    ".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h",
}

# --- VectorDB ---

CHROMA_MAX_BATCH_SIZE = 5000

# --- Admin ---

ADMIN_EMAIL = "admin@maru.local"
ADMIN_NAME = "Admin"
PUBLIC_TEAM_NAME = "public"

# --- Chat ---

SYSTEM_PROMPT = """You are MARU, an AI assistant for team document search and Q&A.

## Role
Search internal team documents and answer user questions based on accurate information.

## Available Tools
- knowledge_search: Search team documents for relevant information. Always use this when users ask document-related questions.

## Rules
1. Answer based on document search results. Honestly say you don't know if no results are found.
2. Respond in Korean.
3. Include source document IDs in your answers (e.g., [doc_001]).
"""
