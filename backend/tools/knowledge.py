import os
from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_openai import OpenAIEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

import sys
import time
import threading

class SpinnerTimer:
    def __init__(self, message="Processing"):
        self.message = message
        self.is_running = False
        self._thread = None
        self.start_time = 0

    def _spin(self) -> None:
        while self.is_running:
            elapsed = time.time() - self.start_time
            sys.stdout.write(f"\r[⏳] {self.message}... ({elapsed:.1f}s)")
            sys.stdout.flush()
            time.sleep(0.1) 

    def start(self) -> None:
        self.is_running = True
        self.start_time = time.time()
        self._thread = threading.Thread(target=self._spin)
        self._thread.start()

    def stop(self) -> float:
        self.is_running = False
        if self._thread:
            self._thread.join()

        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()
        return time.time() - self.start_time

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
        if not self.retriever:
            return {"error": "Knowledge base is empty. Please add files to ./Papers and restart."}

        print(f"\n[📚] Orbit is scanning local documents for: '{query}'...")

        timer = SpinnerTimer(message="Reading and ranking chunks")
        timer.start()

        try:
            docs = self.retriever.invoke(query)

            elapsed_time = timer.stop()

            if not docs:
                print(f"[📚] Local Search: No relevant info found. ({elapsed_time:.1f}s)")
                return {"result": "No relevant local information found."}
            
            print(f"[📚] Local Search: Successfully retrieved {len(docs)} chunks! ({elapsed_time:.1f}s)")
            
            context = "\n\n---\n\n".join(
                [f"[Source: {doc.metadata.get('source', 'Unknown')}]\n{doc.page_content}" for doc in docs]
            )

            return {"result": context}
        
        except Exception as e:
            timer.stop()
            print(f"[⚠️] Local Search failed: {e}")
            return {"error": str(e)}