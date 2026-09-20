import json
from pathlib import Path

import pymupdf


def extract_pdf_blocks(pdf_path: str) -> dict:
    """
    Extract a PDF page-by-page while preserving:
    - blocks
    - lines
    - spans
    - text
    - bounding boxes
    - font information
    - font size
    - text flags

    No reading-order correction is performed here.
    """

    pdf_path = Path(pdf_path)

    doc = pymupdf.open(pdf_path)

    document = {
        "source_pdf": pdf_path.name,
        "page_count": len(doc),
        "pages": []
    }

    global_block_id = 0
    global_line_id = 0
    global_span_id = 0

    for page_number, page in enumerate(doc, start=1):

        page_dict = page.get_text("dict")

        page_data = {
            "page_number": page_number,
            "width": page.rect.width,
            "height": page.rect.height,
            "blocks": []
        }

        for block in page_dict["blocks"]:

            # Image blocks don't contain "lines"
            if "lines" not in block:
                continue

            global_block_id += 1

            block_data = {
                "block_id": f"B{global_block_id:05d}",
                "bbox": [
                    round(x, 2)
                    for x in block["bbox"]
                ],
                "lines": []
            }

            for line in block["lines"]:

                global_line_id += 1

                line_data = {
                    "line_id": f"L{global_line_id:06d}",
                    "bbox": [
                        round(x, 2)
                        for x in line["bbox"]
                    ],
                    "spans": []
                }

                for span in line["spans"]:

                    text = span["text"]

                    if not text.strip():
                        continue

                    global_span_id += 1

                    span_data = {
                        "span_id": f"S{global_span_id:07d}",
                        "text": text,
                        "bbox": [
                            round(x, 2)
                            for x in span["bbox"]
                        ],
                        "font": span["font"],
                        "size": round(span["size"], 2),
                        "flags": span["flags"]
                    }

                    line_data["spans"].append(span_data)

                if line_data["spans"]:
                    block_data["lines"].append(line_data)

            if block_data["lines"]:
                page_data["blocks"].append(block_data)

        document["pages"].append(page_data)

    doc.close()

    return document


def save_document(document: dict, output_path: str):
    """Save extracted document as JSON."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            document,
            f,
            ensure_ascii=False,
            indent=2
        )


if __name__ == "__main__":
    file_path = r"E:\HILLUL\Project Associate - I\SDEP\Indigenous fermented foods of Northeast India Emerging opportunities in functional foods, microbiota-driven nutrition and safety perspectives.pdf"
    pdf_path = file_path
    output_path = f"data/processed/{Path(pdf_path).name}.json"

    document = extract_pdf_blocks(pdf_path)

    save_document(document, output_path)

    print(
        f"Extracted {document['page_count']} pages "
        f"from {document['source_pdf']}"
    )

    