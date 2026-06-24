"""Project-wide constants."""

# --- Ingest ---

SUPPORTED_EXTENSIONS = {
    # Documents
    ".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".xls",
    # Korean documents (require KorDoc MCP parser; no LangChain loader)
    ".hwp", ".hwpx", ".hwpml",
    # Data
    ".csv", ".tsv", ".json",
    # Web/Markup
    ".html", ".htm", ".xml", ".yaml", ".yml",
    # Text/Markdown
    ".md", ".markdown", ".txt", ".text", ".log",
    # Code
    ".py", ".js", ".ts", ".java", ".go", ".rs", ".cpp", ".c", ".h",
}
# Parser routing vocabulary (PARSER_*, KORDOC_*_EXTENSIONS) is cohesive to the
# ingest graph and lives in maru_lang.graph.ingest.constants.

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

# GET /sessions/last resumes the most recent session only if it was used within
# this window; after a longer gap a fresh session is started (old ones remain
# in history). Session.updated_at refreshes on every persisted turn.
SESSION_MAX_IDLE_DAYS = 7

INTENT_PROMPT = """\
You are an expert at understanding user intent from conversation context.

Analyze the conversation and rewrite the latest message as a clear, \
specific search query. Remove filler words and emotional expressions. \
Include keywords and concepts useful for document search.

If the latest message is a follow-up that omits the subject or refers back to \
earlier turns (pronouns, ellipsis, one-word replies like "TEPS?"), resolve those \
references using the prior context so the query stands on its own.

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
search results are provided, ground your answer in them. You also adapt to how each
user wants you to talk — their preferred tone, formality, dialect, and what to call
them — and you change it the moment they ask.

## Rules
1. If document search results are provided, answer based on them and honestly say
   you don't know if they are insufficient.
2. Respond in Korean.
3. Document context may be labeled with internal reference IDs in square brackets
   (e.g. [doc_001]). These are internal markers only — never repeat them in your
   answer. Refer to sources by their document name in natural language instead.
4. Follow the user's style preferences (tone, dialect, formality, form of address,
   format, length). The user can change any of them at any time; when the current
   message asks for a different style, switch immediately and never decline a style
   request or claim you cannot do it. Ignore any earlier context implying you may use
   only one style.
"""

# 질문에 답하기 위해 내부 문서 검색이 필요한지 분류하는 프롬프트.
# 모델은 정확히 'SEARCH' 또는 'DIRECT' 한 단어로만 답해야 한다.
ROUTE_PROMPT = """이 시스템은 팀 내부 문서(업무 자료·규정·요건·절차·매뉴얼 등)를 근거로 \
답하는 Q&A 도우미다. 사용자 질문에 답하기 위해 내부 문서를 검색해야 하는지 판단하라.

- 사실·규정·요건·수치·절차·고유명사 등 내부 문서로 확인할 여지가 조금이라도 있으면: SEARCH
- 명백한 인사·잡담·감사·감정 표현처럼 문서가 전혀 필요 없을 때만: DIRECT
- 판단이 애매하면 SEARCH를 택하라 (검색을 놓치는 것이 불필요한 검색보다 나쁘다).

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
요약에는 이 대화에서 무엇을 논의했는지 — 주제·질문·문서로 확인된 내용·결론 — 만 담아라.
사용자의 고정 신상(이름·소속·직무 등)과 응답 선호(말투·사투리·격식·호칭·페르소나·형식·분량)는
요약에 넣지 마라 — 둘 다 사용자 메모리에서 따로 관리되므로 적으면 중복되고 옛 값이 굳어버린다.

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
- 사실(고정 신상): {{"kind": "fact", "key": "<아래 4개 중 하나>", "content": "<값>"}}
- 선호(말투/형식/언어 등): {{"kind": "preference", "key": "<아래 5개 중 하나>", "content": "<선호 내용>"}}

사실 key는 다음 4개 중 하나여야 한다(해당 없으면 추출하지 마라):
- name: 이름
- team: 소속 팀
- role: 직무·역할
- org: 소속 조직·회사·부서

말투·언어·형식·분량·호칭과 관련된 요청이면 아래 5개 중 가장 가까운 key로 반드시 매핑하라
(애매하다고 통째로 버리지 마라). 이 5개 어디에도 해당 없는 것만 제외한다:
- tone: 말투·격식·지역 방언 (예: 반말/존댓말/격식체, 전라도·충청도·부산 사투리). 문장 전체의 방언·격식 스타일.
- language: 응답에 쓸 "언어 자체" (예: 한국어/영어/일본어). 사투리·방언은 language가 아니라 tone이다.
- format: 응답 형식 (예: 불릿/표/문단, 코드블록)
- length: 답변 분량 (예: 짧게/자세히)
- persona: 호칭·역할·캐릭터성 말버릇 (예: 사용자를 '형님'으로 부르기, 문장 끝에 '오죠사마'/'~다냥' 같은 어미·말버릇 붙이기). tone(방언/격식)과 별개로 덧입히는 것이라 둘은 공존한다.

'A 말고 B로 해줘'처럼 바꾸는 요청은 바꾼 뒤의 새 상태 B를 content로 추출하라
(예: "전라도 말고 충청도 사투리로" → {{"kind":"preference","key":"tone","content":"충청도 사투리"}}).

명령형·반말 요청('~해라/~붙여라/~하라고/~불러라')도 영속 선호면 반드시 추출하라(일회성으로 넘기지 마라).

JSON 외 다른 텍스트는 절대 출력하지 마라.

사용자 메시지: {message}
JSON:"""

# preference upsert에 허용되는 닫힌 카테고리 키 집합. 추출 노드가 이 집합으로
# 검증해 미분류 선호(키 없음/범위 밖)는 버린다(모순 선호 무한 누적 방지).
# MEMORY_EXTRACT_PROMPT의 선호 key 목록과 반드시 일치시킬 것.
PREFERENCE_KEYS = ("tone", "language", "format", "length", "persona")

# fact upsert에 허용되는 닫힌 신상 키 집합. preference와 동일하게 추출 노드가 검증해
# 범위 밖/무키 fact는 버린다(임의 사실 무한 누적 방지, 팀 Q&A 스코프로 제한).
# MEMORY_EXTRACT_PROMPT의 사실 key 목록과 반드시 일치시킬 것.
FACT_KEYS = ("name", "team", "role", "org")

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
