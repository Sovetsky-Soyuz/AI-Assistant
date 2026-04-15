import os
from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader
# from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.prompts import ChatPromptTemplate
# from pprint import pprint
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever, ContextualCompressionRetriever
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder



# ---------------------------------------------------------
# 1. TẢI VÀ CHIA NHỎ DỮ LIỆU
# ---------------------------------------------------------
loader = DirectoryLoader(
    path="./Papers",
    glob="**/*.*",
    loader_cls=UnstructuredFileLoader,
    show_progress=True,
    use_multithreading=True
)

docs = loader.load()

# ---------------------------------------------------------
# 2. KHỞI TẠO EMBEDDING & CHIA NHỎ THEO NGỮ NGHĨA (Semantic)
# ---------------------------------------------------------
# Khởi tạo bge-m3 TRƯỚC để SemanticChunker có công cụ đọc hiểu
embeddings = OpenAIEmbeddings(
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",
    model="text-embedding-bge-m3",
    check_embedding_ctx_length=False
)

# Thay thế Recursive bằng SemanticChunker
text_splitter = SemanticChunker(
    embeddings,
    breakpoint_threshold_type="percentile"
)

# Quá trình này sẽ hơi lâu hơn bình thường vì nó phải nhúng (embed)
# từng câu văn để đo lường khoảng cách ngữ nghĩa rồi mới cắt.
print("Semantic Chunking...")
splits = text_splitter.split_documents(docs)


text_splitter = SemanticChunker(
    embeddings=embeddings,
    breakpoint_threshold_type="percentile"
)

# ---------------------------------------------------------
# 3. CẤU HÌNH EMBEDDING LOCAL (Qua LM Studio)
# ---------------------------------------------------------
# Khởi tạo Retriever 1: Keyword Search (BM25)
bm25_retriever = BM25Retriever.from_documents(splits)
bm25_retriever.k = 5 # Lấy top 5 từ khóa chính xác nhất

vectorstore = FAISS.from_documents(
    documents=splits,
    embedding=embeddings,
    distance_strategy=DistanceStrategy.COSINE
)

# Dùng MMR để đa dạng hóa ngữ cảnh cho FAISS
faiss_retriever = vectorstore.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 5, "fetch_k": 20, "lambda_mult": 0.5}
)

# C. Trộn cả hai lại bằng EnsembleRetriever (Hybrid)
ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, faiss_retriever],
    weights=[0.5, 0.5] # Trọng số: 50% nghe theo BM25, 50% nghe theo FAISS
)

# Khởi tạo Reranker
rerank_model = HuggingFaceCrossEncoder(model_name="BAAI/bge-reranker-v2-m3")
compressor = CrossEncoderReranker(model=rerank_model, top_n=3)

compression_retriever = ContextualCompressionRetriever(
    base_compressor=compressor,
    base_retriever=ensemble_retriever
)

# ---------------------------------------------------------
# 3. CẤU HÌNH LLM LOCAL (Qua LM Studio)
# ---------------------------------------------------------
llm = ChatOpenAI(
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",
    model="google/gemma-3-4b",
    temperature=0,

)

template = (
    "You are a strict, citation-focused assistant for a private knowledge base.\n"
    "RULES:\n"
    "1) Read the context carefully. Does it contain the answer to the question? (Yes/No).\n"
    "2) If No, you MUST output EXACTLY: \"I don't know based on the provided documents.\" Do not add anything else.\n"
    "3) If Yes, answer the question using ONLY the provided context.\n"
    "4) If applicable, cite the source as (source:page) using the metadata.\n\n"
    "Context:\n{context}\n\n"
    "Question: {question}"
)


prompt = ChatPromptTemplate.from_template(template)

rag_chain = (
    {"context": compression_retriever, "question": RunnablePassthrough()}
    | prompt
    | llm
    | StrOutputParser()
)


# ---------------------------------------------------------
# 4. CHẠY CHATBOT
# ---------------------------------------------------------


print("\nThe system is ready! Type 'exit' to exit.")
while True:
    question = input("\nQuestion: ")

    # Xử lý trường hợp người dùng ấn Enter trống
    if not question.strip():
        print("Please enter your question! Or type 'exit' to exit.")
        continue

    if question.lower() == 'exit':
        break

    try:
        answer = rag_chain.invoke(question)
        print("\nAnswer:", answer)
    except Exception as e:
        print(f"\n[ERROR]: {e}")