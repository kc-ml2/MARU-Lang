"""Print the chat graph as a Mermaid diagram, traced from the actual compiled graph.

Keeps the README architecture diagram accurate — regenerate with:

    python scripts/draw_graph.py

The graph *topology* doesn't depend on the real LLM/retriever, so we compile it
with a stub model and stubbed component factories (no API key / embeddings needed).
"""
from unittest.mock import MagicMock, patch

from langchain_core.language_models import BaseChatModel

import maru_lang.configs.manager as cfg_mod
from maru_lang.configs.models import MaruConfig


def main() -> None:
    cfg_mod._config = MaruConfig()  # defaults; avoids needing maru_config.yaml

    model = MagicMock(spec=BaseChatModel)
    model.bind_tools = MagicMock(return_value=model)

    with patch("maru_lang.graph.rag.graph.build_retriever", return_value=MagicMock()), \
         patch("maru_lang.graph.rag.graph.build_compressor", return_value=None):
        from maru_lang.graph.rag.graph import create_rag_graph
        graph = create_rag_graph(model=model)

    mermaid = graph.get_graph().draw_mermaid()
    # Drop the `--- config ... ---` init frontmatter for portable Markdown rendering.
    if mermaid.startswith("---"):
        mermaid = mermaid.split("---", 2)[-1].lstrip("\n")
    print(mermaid)


if __name__ == "__main__":
    main()
