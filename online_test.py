import pymupdf4llm
import pathlib

md_text = pymupdf4llm.to_markdown("C:/Users/qt321/AI_Assistant/knowledge_base/High-Fidelity Simultaneous Speech-To-Speech Translation.pdf")

md_result = pathlib.Path("C:/Users/qt321/AI_Assistant/knowledge_base/High-Fidelity Simultaneous Speech-To-Speech Translation.md").write_text(md_text, encoding="utf-8")


# print(md_result)