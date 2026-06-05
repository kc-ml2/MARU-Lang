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

# --- Task queue (ARQ) ---

# Single source of truth for the ingest job name: the enqueue side
# (api/endpoints/ingest.py) and the worker registration (worker.py) must agree.
INGEST_TASK_NAME = "ingest_document_task"

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

# Feedback: scores at or below this trigger the reason-collection step.
FEEDBACK_REASON_THRESHOLD = 3

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
Answer user questions based on accurate information. When internal team document
search results are provided, ground your answer in them.

## Rules
1. If document search results are provided, answer based on them and honestly say
   you don't know if they are insufficient.
2. Respond in Korean.
3. Document context may be labeled with internal reference IDs in square brackets
   (e.g. [doc_001]). These are internal markers only — never repeat them in your
   answer. Refer to sources by their document name in natural language instead.
"""

# 질문에 답하기 위해 내부 문서 검색이 필요한지 분류하는 프롬프트.
# 모델은 정확히 'SEARCH' 또는 'DIRECT' 한 단어로만 답해야 한다.
ROUTE_PROMPT = """다음 사용자 질문에 정확히 답하려면 내부 팀 문서를 검색해야 하는가?

- 문서/자료/내부 정보가 필요하면: SEARCH
- 인사·잡담·일반 상식 등 검색 없이 답할 수 있으면: DIRECT

오직 'SEARCH' 또는 'DIRECT' 한 단어로만 답하라.

질문: {question}
판단:"""

# 한 턴(질문+답변)을 짧게 요약하는 프롬프트. Conversation.summary에 저장.
TURN_SUMMARY_PROMPT = """다음 한 번의 질의응답을 1~2문장으로 간결히 요약하라. 핵심 질문과 답변 요지만 담아라.

질문: {question}
답변: {answer}

요약:"""

# 기존 세션 요약 + 이번 턴 → 갱신된 롤링 요약. Session.summary에 저장.
SESSION_SUMMARY_PROMPT = """아래 [기존 요약]에 [이번 턴]을 반영해 세션 전체의 최신 누적 요약을 만들어라.
간결하게 핵심 맥락만 유지하고 불필요한 반복은 제거하라.

[기존 요약]
{previous}

[이번 턴]
질문: {question}
답변: {answer}

[갱신된 요약]:"""

# 사용자 메시지에서 영구 기억할 사실/선호를 추출하는 프롬프트. JSON 배열만 출력.
MEMORY_EXTRACT_PROMPT = """사용자 메시지에서 앞으로 계속 기억해야 할 '영구적인 사실/선호'만 추출하라.
일회성 질문, 잡담, 검색 요청은 제외한다.

JSON 배열로만 출력하라 (해당 없으면 []):
- 사실(이름/소속/직무 등 고정 정보): {{"kind": "fact", "key": "<짧은 키, 예: name>", "content": "<값>"}}
- 선호(말투/형식/언어 등): {{"kind": "preference", "content": "<선호 내용>"}}

JSON 외 다른 텍스트는 절대 출력하지 마라.

사용자 메시지: {message}
JSON:"""

# 사용자 요청에 가장 적합한 그래프(처리기)를 고르는 라우터 프롬프트. id 하나만 출력.
GRAPH_ROUTER_PROMPT = """다음 사용자 요청을 처리하기에 가장 적합한 그래프를 고르라.

선택지 (id: 설명):
{options}

위 id 중 정확히 하나만 출력하라. 다른 텍스트는 절대 출력하지 마라.

사용자 요청: {message}
선택:"""


# --- Integration test provider gates ---
# Maps an LLM provider to the env var that must be present to run its
# integration tests. Hosted APIs need an API key; self-hosted servers need a
# base URL (explicit opt-in so `pytest -m integration` won't hang on a missing
# local server). Shared by the e2e tests and the `maru test` CLI.
PROVIDER_GATE_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
    "vllm": "VLLM_BASE_URL",
}
