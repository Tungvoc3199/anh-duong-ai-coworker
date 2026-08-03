from sqlalchemy.orm import Session

from app.context_builder.builder import ContextBuilder
from app.memory.repository import MemoryRepository
from app.memory.retrieval import HybridMemoryRetriever


def create_context_builder(session: Session) -> ContextBuilder:
    """Compose CB-1 dependencies without performing retrieval or database I/O."""

    repository = MemoryRepository(session)
    retriever = HybridMemoryRetriever(repository)
    return ContextBuilder(retriever)

