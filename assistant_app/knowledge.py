import os
from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

class KnowledgeService:
    def __init__(self, docs_dir: str = "./Papers"):
        self.docs_dir = docs_dir
        self.retriever = None
        self._initialize_knowledge_base()

    def _initialize_knowledge_base(self) -> None:
        if not os.path.exists(self.docs_dir):
            os.makedirs(self.docs_dir)
            print(f"Created directory {self.docs_dir}. Please add your documents here.")
            return

        print("Loading local documents into Orbit's memory...")
        loader = DirectoryLoader(
            path=self.docs_dir,
            glob="**/*.*",
            loader_cls=UnstructuredFileLoader,
            show_progress=True,
            use_multithreading=True
        )
        docs = loader.load()

        if not docs:
            print("No documents found in the local folder.")
            return

        MARKDOWN_SEPARATORS = [
            "\n#{1,6} ", 
            "'''\n", 
            "\n\\*\\*\\**\n", 
            "\n---+\n", 
            "\n___+\n", 
            "\n\n", 
            "\n", 
            " ", 
            ""
        ]

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200,
            chunk_overlap=200,
            add_start_index=True,
            strip_whitespace=True,
            separators=MARKDOWN_SEPARATORS
        )
        splits = text_splitter.split_documents(docs)

        # Khởi tạo embedding qua LM Studio (chắc chắn LM Studio đang chạy bge-m3 ở port 1234)
        embeddings = OpenAIEmbeddings(
            base_url="http://127.0.0.1:1234/v1",
            api_key="lm-studio",
            model="text-embedding-bge-m3",
            check_embedding_ctx_length=False
        )

        bm25_retriever = BM25Retriever.from_documents(splits)
        bm25_retriever.k = 5

        vectorstore = FAISS.from_documents(
            documents=splits,
            embedding=embeddings,
            distance_strategy=DistanceStrategy.COSINE
        )

        faiss_retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 5, "fetch_k": 20, "lambda_mult": 0.5}
        )

        self.retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, faiss_retriever],
            weights=[0.5, 0.5]
        )
        print("Orbit Local Knowledge Base is ready!")

    def search(self, query: str) -> dict:
        """Orbit sẽ gọi hàm này khi cần tìm tài liệu local"""
        if not self.retriever:
            return {"error": "Knowledge base is empty. Please add files to ./Papers and restart."}

        try:
            docs = self.retriever.invoke(query)
            if not docs:
                return {"result": "No relevant local information found."}
            
            # Đóng gói kết quả gửi lại cho Orbit đọc hiểu
            context = "\n\n---\n\n".join(
                [f"[Source: {doc.metadata.get('source', 'Unknown')}]\n{doc.page_content}" for doc in docs]
            )
            return {"result": context}
        except Exception as e:
            return {"error": str(e)}