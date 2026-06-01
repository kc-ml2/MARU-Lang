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

# --- Network ---

LOCALHOST_HOSTS = {"127.0.0.1", "::1", "localhost"}

# --- Admin ---

ADMIN_EMAIL = "admin@maru.local"
ADMIN_NAME = "Admin"
PUBLIC_TEAM_NAME = "public"
CLI_DEVICE_ID = "maru-cli"

# --- Chat ---

INTENT_PROMPT = """\
You are an expert at understanding user intent from conversation context.

Analyze the conversation and rewrite the latest message as a clear, \
specific search query. Remove filler words and emotional expressions. \
Include keywords and concepts useful for document search.

Return only the rewritten query. No explanation needed."""

KEYWORD_PROMPT = """\
Extract 3-7 search keywords from the following query.
Focus on core nouns and key concepts. Remove all stopwords.
Return keywords separated by spaces. No explanation needed.

Example:
- Query: "How do I apply for company vacation leave?"
- Keywords: "company vacation leave application process"

Query: {query}

Keywords:"""

# --- RAG Evaluate ---

RAG_EVALUATE_MIN_DOCS = 2
RAG_EVALUATE_MIN_AVG_SCORE = 0.3
RAG_EVALUATE_MAX_RETRIES = 2

RAG_EVALUATE_PROMPT = """\
You are evaluating search results for a user query.
Determine if the retrieved documents sufficiently answer the query.
Answer only "sufficient" or "insufficient". No explanation needed.

Query: {query}

Documents:
{documents}

Verdict:"""

# --- Chat ---

SYSTEM_PROMPT = """You are MARU, an AI assistant for team document search and Q&A.

## Role
Search internal team documents and answer user questions based on accurate information.

## Available Tools
- knowledge_search: Search team documents for relevant information.

## Rules
1. Call each tool at most once per user message. Do not retry the same tool with a rephrased query.
2. Answer based on document search results. Honestly say you don't know if no results are found.
3. Respond in Korean.
"""
