from docling.document_converter import DocumentConverter
# from docling.document_loader import DocumentLoader

source_file = "C:/Users/qt321/AI_Assistant/knowledge_base/High-Fidelity Simultaneous Speech-To-Speech Translation.pdf"

converter = DocumentConverter()
doc = converter.convert(source_file).document

print(doc.export_to_markdown())