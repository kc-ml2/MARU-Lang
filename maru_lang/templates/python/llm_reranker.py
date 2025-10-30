"""LLM Reranker Agent - Reranks search results using LLM evaluation"""
import json
from typing import Dict, Any, Optional, List, Tuple
from maru_lang.pluggable.agents.base import BaseAgent, AgentResult
from maru_lang.core.vector_db.retrieve_document import RetrieveDocument


class LLMRerankerAgent(BaseAgent):
    """Agent for reranking search results using LLM-based relevance evaluation"""

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)

    async def _setup(self) -> None:
        """Initialize reranker capabilities"""
        # No special setup needed for LLM reranker
        pass

    async def execute(
        self,
        query: str,
        documents: List[RetrieveDocument],
        top_k: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> AgentResult:
        """
        Execute reranking using LLM evaluation

        Args:
            query: Search query
            documents: List of RetrieveDocument objects to rerank
            top_k: Return only top k results (None = return all)
            metadata: Optional metadata
            **kwargs: Additional parameters

        Returns:
            AgentResult with data as List[(idx, score)] for compatibility with retriever
        """
        if not documents:
            return AgentResult(
                success=True,
                result="",
                data=[]  # Return empty list for retriever
            )

        try:
            # Extract document texts from RetrieveDocument objects
            document_texts = [doc.page_content for doc in documents]

            # Format documents for LLM prompt
            documents_str = self._format_documents(document_texts)

            # Get relevance scores from LLM
            rerank_result = await self._rerank_with_llm(
                query,
                documents_str,
            )

            # Process and sort results - returns List[(idx, score)]
            ranked_tuples = self._process_rerank_result(
                rerank_result,
                len(documents),
                top_k
            )

            return AgentResult(
                success=True,
                result=f"Reranked {len(documents)} documents",
                data=ranked_tuples,  # List[(idx, score)] format for retriever
                metadata={
                    'rerank_method': 'llm',
                    'original_count': len(documents),
                    'returned_count': len(ranked_tuples)
                }
            )

        except Exception as e:
            # Fallback: return original order as List[(idx, score)]
            indices = list(range(len(documents)))
            if top_k:
                indices = indices[:top_k]

            fallback_data = [(idx, 1.0) for idx in indices]

            return AgentResult(
                success=True,
                result="Fallback to original order",
                data=fallback_data,  # List[(idx, score)] format
                metadata={
                    'rerank_method': 'fallback',
                    'error': str(e)
                }
            )

    def _format_documents(self, documents: List[str]) -> str:
        """Format documents for LLM prompt"""
        formatted = []
        for idx, doc in enumerate(documents):
            # Truncate very long documents to avoid token limits
            doc_preview = doc[:500] + "..." if len(doc) > 500 else doc
            formatted.append(f"[{idx}] {doc_preview}")

        return "\n\n".join(formatted)

    async def _rerank_with_llm(
        self,
        query: str,
        documents: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Use LLM to evaluate document relevance"""
        # Prepare tool definition
        tools = [
            tool.to_dict(tool_name=tool_name) for tool_name, tool in self.config.tools.items()
        ]

        prompts = self.config.prompts

        user_prompt = prompts.user_prompt_template.format(
            query=query,
            documents=documents
        )

        override_params = self.get_override_params()

        # Prepare messages
        messages = [
            {"role": "system", "content": prompts.system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.request_with_tools_and_fallback(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            **override_params,
        )

        return response

    def _process_rerank_result(
        self,
        result: Dict[str, Any],
        document_count: int,
        top_k: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Process and validate rerank result

        Returns:
            List[(idx, score)] in descending order by score
        """
        # Extract arguments from tool_calls structure
        tool_calls = result.get('tool_calls', [])
        if tool_calls:
            # Get arguments from first tool call
            arguments = tool_calls[0].get('function', {}).get('arguments', {})
            # If arguments is a string, parse it
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
        else:
            # Fallback: assume result is already the arguments
            arguments = result

        # Extract document scores
        document_scores = arguments.get('document_scores', [])

        # Create (index, score) tuples
        scored_docs: List[Tuple[int, float]] = []
        for item in document_scores:
            idx = item.get('index', -1)
            score = item.get('score', 0.0)

            # Validate index
            if 0 <= idx < document_count:
                scored_docs.append((idx, float(score)))

        # Fill in missing indices with score 0.0
        scored_indices = {idx for idx, _ in scored_docs}
        for idx in range(document_count):
            if idx not in scored_indices:
                scored_docs.append((idx, 0.0))

        # Sort by score (descending)
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # Apply top_k limit
        if top_k:
            scored_docs = scored_docs[:top_k]

        return scored_docs
