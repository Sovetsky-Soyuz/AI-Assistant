from langchain_community.document_loaders import DirectoryLoader, UnstructuredFileLoader, PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.prompts import ChatPromptTemplate
from pprint import pprint
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
# from dotenv import load_dotenv
#
# load_dotenv()


# ---------------------------------------------------------
# 1. TẢI VÀ CHIA NHỎ DỮ LIỆU
# ---------------------------------------------------------
loader = DirectoryLoader(
    path="./Papers",
    glob="**/*.*",
    loader_cls=UnstructuredFileLoader,
    # loader_kwargs={"mode": "elements"},
    show_progress=True,
    use_multithreading=True
)

docs = loader.load()

# 2. CẮT NHỎ DỮ LIỆU
MARKDOWN_SEPERATORS = ["\n#{1,6} ", "'''\n", "\n\\*\\*\\**\n", "\n---+\n", "\n___+\n", "\n\n", "\n", " ", ""]

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1200,
    chunk_overlap=200,
    add_start_index=True,
    strip_whitespace=True,
    separators=MARKDOWN_SEPERATORS
)

splits = text_splitter.split_documents(docs)

# 3. IN RA XEM THÀNH QUẢ ĐÃ ĐƯỢC BĂM NHỎ CHƯA
print(f"Số lượng file PDF gốc: {len(docs)}")
print(f"Số lượng chunk (đoạn nhỏ) sau khi cắt: {len(splits)}")

# In thử chunk thứ 5 ra xem metadata có báo số trang chuẩn không nhé:
print("\n--- CHUNK THỨ 5 ---")
pprint(splits[4])