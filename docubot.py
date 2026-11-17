"""
Core DocuBot class responsible for:
- Loading documents from the docs/ folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import re
import glob

# -----------------------------------------------------------
# Text helpers used by indexing, scoring, and retrieval
# -----------------------------------------------------------

# Words that carry no meaning for search ("where is the ...").
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "be", "do", "does", "did", "i",
    "you", "we", "it", "my", "our", "your", "to", "of", "in", "on", "for",
    "and", "or", "by", "with", "from", "at", "as", "this", "that", "these",
    "those", "there", "any", "what", "which", "where", "when", "how", "who",
    "why", "can", "should", "will", "me", "about", "into", "get", "use",
}

# Extra points for each query term that appears in a section's heading.
HEADING_BONUS = 0.5

# Extra points when a route/path from the query (e.g. "/api/users") is
# exactly the thing a section heading documents.
EXACT_PATH_BONUS = 2


def stem(word):
    """Very small suffix stripper so 'generated'/'generation' and 'users'/'user' match."""
    for suffix in ("ions", "ing", "ion", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    # 'stores' -> 'store' -> 'stor' so it matches 'stored' -> 'stor'
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def tokenize(text):
    """Lowercase, split on anything that is not a letter/digit/underscore, drop stopwords, stem."""
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


def split_into_sections(text):
    """
    Split a markdown document into sections: each heading line starts a new
    section and keeps its body with it. Sections with no real content are dropped.
    """
    sections, current = [], []
    for line in text.splitlines():
        if line.startswith("#") and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    # A lone heading (e.g. "## Tables") is not useful evidence.
    return [s for s in sections if len(s.splitlines()) > 1]


def min_score_for(query_terms):
    """
    Guardrail threshold. A section must match at least 2 distinct query terms
    (or every term, for one-word queries). One incidental word overlap is
    not evidence.
    """
    return min(2, len(query_terms))

class DocuBot:
    def __init__(self, docs_folder="docs", llm_client=None):
        """
        docs_folder: directory containing project documentation files
        llm_client: optional Gemini client for LLM based answers
        """
        self.docs_folder = docs_folder
        self.llm_client = llm_client

        # Load documents into memory
        self.documents = self.load_documents()  # List of (filename, text)

        # Build a retrieval index (implemented in Phase 1)
        self.index = self.build_index(self.documents)

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_documents(self):
        """
        Loads all .md and .txt files inside docs_folder.
        Returns a list of tuples: (filename, text)
        """
        docs = []
        pattern = os.path.join(self.docs_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                docs.append((filename, text))
        return docs

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def build_index(self, documents):
        """
        Build a tiny inverted index mapping normalized words to the documents
        they appear in, e.g. {"token": ["API_REFERENCE.md", "AUTH.md"], ...}.

        Also splits every document into sections (self.sections) so retrieval
        can return small, focused snippets instead of whole files.
        """
        index = {}
        self.sections = []  # list of (filename, section_text)

        for filename, text in documents:
            for word in set(tokenize(text)):
                index.setdefault(word, []).append(filename)
            for section in split_into_sections(text):
                self.sections.append((filename, section))

        return index

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def score_document(self, query, text):
        """
        Relevance score = number of distinct query terms present in the text,
        plus a bonus for each query term that appears in the section heading
        (headings are a strong signal of what a section is about).
        """
        query_terms = set(tokenize(query))
        if not query_terms:
            return 0

        text_terms = set(tokenize(text))
        first_line = text.splitlines()[0] if text.strip() else ""
        heading_terms = set(tokenize(first_line)) if first_line.startswith("#") else set()

        matches = query_terms & text_terms
        heading_bonus = HEADING_BONUS * len(query_terms & heading_terms)

        # Paths like "/api/projects/<project_id>" should prefer the section
        # whose heading names that exact route, not just a similar one.
        path_bonus = 0
        if first_line.startswith("#"):
            heading_paths = set(re.findall(r"/\S+", first_line))
            for path in re.findall(r"/\S+", query):
                if path.rstrip("?.,").lower() in {p.lower() for p in heading_paths}:
                    path_bonus = EXACT_PATH_BONUS

        return len(matches) + heading_bonus + path_bonus

    def retrieve(self, query, top_k=3):
        """
        Return up to top_k (filename, section_text) pairs, best first.

        Steps:
        1. Use the index to find candidate files containing any query term.
        2. Score each section of those files.
        3. Guardrail: drop sections that do not clear min_score_for(query).
        4. Sort by score (ties: shorter section first) and keep top_k.
        """
        query_terms = set(tokenize(query))
        if not query_terms:
            return []

        candidate_files = set()
        for term in query_terms:
            candidate_files.update(self.index.get(term, []))

        threshold = min_score_for(query_terms)
        scored = []
        for filename, section in self.sections:
            if filename not in candidate_files:
                continue
            score = self.score_document(query, section)
            if score >= threshold:
                scored.append((score, filename, section))

        scored.sort(key=lambda item: (-item[0], len(item[2])))
        return [(filename, section) for _, filename, section in scored[:top_k]]

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=3):
        """
        Phase 1 retrieval only mode.
        Returns raw snippets and filenames with no LLM involved.
        """
        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        formatted = []
        for filename, text in snippets:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=3):
        """
        Phase 2 RAG mode.
        Uses student retrieval to select snippets, then asks Gemini
        to generate an answer using only those snippets.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.documents)
