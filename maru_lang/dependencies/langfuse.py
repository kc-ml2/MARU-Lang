from fastapi import Request
from typing import AsyncGenerator
from maru_lang.tracing import langfuse_wrapper


class LangfuseContext:
    def __init__(
        self,
        request: Request,
    ):
        self.is_available = langfuse_wrapper.is_available and langfuse_wrapper.langfuse is not None
        self.request = request
        self.span = None
        self.span_context = None
    
    def update_metadata(self, **kwargs):
        if self.is_available and self.span:
            try:
                # metadata가 없을 수 있으므로 안전하게 처리
                current_metadata = getattr(self.span, 'metadata', {}) or {}
                self.span.update_trace(
                    metadata={
                        **current_metadata,
                        **kwargs
                    }
                )
            except Exception as e:
                print(f"Warning: Failed to update metadata: {e}")

    def update_trace(self, **kwargs):
        if self.is_available and self.span:
            try:
                self.span.update_trace(**kwargs)
            except Exception as e:
                print(f"Warning: Failed to update trace: {e}")

    def update_span(self, **kwargs):
        if self.is_available and self.span:
            try:
                self.span.update(**kwargs)
            except Exception as e:
                print(f"Warning: Failed to update span: {e}")

    def __enter__(self):
        if self.is_available:
            try:
                self.span_context = langfuse_wrapper.langfuse.start_as_current_span(
                    name=f"API-{self.request.url.path}"
                )
                self.span = self.span_context.__enter__()
            except Exception as e:
                print(f"Warning: Failed to start Langfuse span: {e}")
                self.is_available = False
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        if self.is_available and self.span_context:
            try:
                self.span_context.__exit__(exc_type, exc_value, traceback)
            except Exception as e:
                print(f"Warning: Failed to end Langfuse span: {e}")

async def get_langfuse_context(request: Request) -> AsyncGenerator[LangfuseContext, None]:
    """FastAPI 의존성으로 Langfuse 컨텍스트 제공"""

    langfuse_context = LangfuseContext(request)
    with langfuse_context as context:
        if context.is_available:
            context.update_metadata(
                endpoint=request.url.path,
                method=request.method,
                user_agent=request.headers.get("User-Agent", "unknown")
            )
        yield context