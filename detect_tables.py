from docling.document_converter import DocumentConverter

converter = DocumentConverter()

result = converter.convert("paper.pdf")

doc = result.document

for table_idx, table in enumerate(doc.tables):
    print(f"\nTABLE {table_idx + 1}")
    print(table.export_to_dataframe())