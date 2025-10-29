"""
대화 히스토리 관련 모델
"""
from typing import List, Tuple, Any, Optional, TYPE_CHECKING
from pydantic import BaseModel, Field
from enum import Enum

if TYPE_CHECKING:
    from maru_lang.core.relation_db.models.chat import Conversation


class MessageRole(str, Enum):
    """메시지 역할"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    """채팅 메시지"""
    role: MessageRole
    content: str
    metadata: Optional[dict] = Field(default=None, description="추가 메타데이터")

    class Config:
        use_enum_values = True


class ChatHistory(BaseModel):
    """대화 히스토리 관리 클래스"""
    messages: List[ChatMessage] = Field(default_factory=list)
    max_turns: Optional[int] = Field(default=None, description="최대 보관 턴 수")

    def add_user_message(self, content: str, metadata: Optional[dict] = None) -> None:
        """사용자 메시지 추가"""
        self.messages.append(ChatMessage(
            role=MessageRole.USER,
            content=content,
            metadata=metadata
        ))
        self._trim_history()

    def add_assistant_message(self, content: str, metadata: Optional[dict] = None) -> None:
        """어시스턴트 메시지 추가"""
        self.messages.append(ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            metadata=metadata
        ))
        self._trim_history()

    def add_turn(self, question: str, answer: str) -> None:
        """대화 턴(질문-답변 쌍) 추가"""
        self.add_user_message(question)
        self.add_assistant_message(answer)

    def _trim_history(self) -> None:
        """최대 턴 수 초과 시 오래된 메시지 제거"""
        if self.max_turns and len(self.messages) > self.max_turns * 2:
            # 한 턴 = 2개 메시지(user + assistant)
            self.messages = self.messages[-(self.max_turns * 2):]

    def get_last_n_turns(self, n: int = 3) -> List[ChatMessage]:
        """마지막 n개 턴 가져오기"""
        return self.messages[-(n * 2):] if len(self.messages) > n * 2 else self.messages

    def get_user_messages(self) -> List[str]:
        """사용자 메시지만 추출"""
        return [msg.content for msg in self.messages if msg.role == MessageRole.USER]

    def get_assistant_messages(self) -> List[str]:
        """어시스턴트 메시지만 추출"""
        return [msg.content for msg in self.messages if msg.role == MessageRole.ASSISTANT]

    def to_dict_list(self) -> List[dict]:
        """딕셔너리 리스트로 변환 (기존 코드 호환용)"""
        return [{"role": msg.role, "content": msg.content} for msg in self.messages]

    def to_openai_format(self) -> List[dict]:
        """OpenAI API 형식으로 변환"""
        return [msg.dict(exclude={"metadata"} if not msg.metadata else set())
                for msg in self.messages]

    def clear(self) -> None:
        """대화 히스토리 초기화"""
        self.messages = []

    @classmethod
    def from_tuples(cls, conversations: List[Tuple[str, str]], max_turns: Optional[int] = None) -> "ChatHistory":
        """튜플 리스트에서 생성 [(question, answer), ...]"""
        history = cls(max_turns=max_turns)
        for question, answer in conversations:
            history.add_turn(question, answer)
        return history

    @classmethod
    def from_dict_list(cls, messages: List[dict], max_turns: Optional[int] = None) -> "ChatHistory":
        """딕셔너리 리스트에서 생성 [{"role": "user", "content": "..."}, ...]"""
        chat_messages = []
        for msg in messages:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                chat_messages.append(ChatMessage(
                    role=msg["role"],
                    content=msg["content"],
                    metadata=msg.get("metadata")
                ))
        return cls(messages=chat_messages, max_turns=max_turns)

    @classmethod
    def from_conversations(cls, conversations: List["Conversation"], max_turns: Optional[int] = None) -> "ChatHistory":
        """
        DB Conversation 객체 리스트에서 생성

        Args:
            conversations: Conversation DB 모델 리스트
            max_turns: 최대 보관할 턴 수

        Returns:
            ChatHistory 인스턴스
        """
        history = cls(max_turns=max_turns)

        for conv in conversations:
            # 질문 추가
            history.add_user_message(
                content=conv.question,
                metadata={"conversation_id": conv.id,
                          "created_at": str(conv.created_at)}
            )
            # 답변 추가
            history.add_assistant_message(
                content=conv.answer,
                metadata={"conversation_id": conv.id,
                          "created_at": str(conv.created_at)}
            )

        return history

    @classmethod
    def from_db_objects(cls, conversations: List[Any], max_turns: Optional[int] = None) -> "ChatHistory":
        """
        DB 객체 리스트에서 생성 (일반적인 경우)
        Conversation 모델이 아닌 다른 형태의 DB 객체용
        """
        history = cls(max_turns=max_turns)
        for i, conv in enumerate(conversations):
            role = MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT
            content = getattr(conv, "content", str(conv))
            history.messages.append(ChatMessage(role=role, content=content))
        return history

    def to_string(
        self,
        n: int = 3,
        only_user_content: bool = False,
    ) -> str:
        """대화 히스토리를 문자열로 변환"""
        messages = self.get_last_n_turns(n)

        if only_user_content:
            # 사용자 질문만 포함
            return "\n".join(
                [f"Q: {msg.content}" for msg in messages if msg.role == MessageRole.USER]
            )

        # 전체 대화 포함 (질문 + 답변)
        return "\n".join(
            [f"{msg.role}: {msg.content}" for msg in messages]
        )

    def __len__(self) -> int:
        """메시지 수 반환"""
        return len(self.messages)

    def __bool__(self) -> bool:
        """대화 히스토리가 있는지 확인"""
        return bool(self.messages)

    def __iter__(self):
        """메시지 순회"""
        return iter(self.messages)

    def __getitem__(self, index: int) -> ChatMessage:
        """인덱스로 메시지 접근"""
        return self.messages[index]
