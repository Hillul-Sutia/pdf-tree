from docling.document_converter import DocumentConverter
from pathlib import Path

PDF_PATH = Path(
    r"E:\HILLUL\Project Associate - I\SDEP\Indigenous fermented foods of Northeast India Emerging opportunities in functional foods, microbiota-driven nutrition and safety perspectives.pdf"
)

converter = DocumentConverter()

result = converter.convert(PDF_PATH)

doc = result.document

for i, table in enumerate(result.document.tables):
    df = table.export_to_dataframe()
    df.to_csv(f"table_{i + 1}.csv", index=False)