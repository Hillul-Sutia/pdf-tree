import pymupdf

file_path = r"E:\HILLUL\Project Associate - I\SDEP\Indigenous fermented foods of Northeast India Emerging opportunities in functional foods, microbiota-driven nutrition and safety perspectives.pdf"

doc = pymupdf.open("research_paper.pdf")

for page_no, page in enumerate(doc, start=1):

    blocks = page.get_text("blocks")

    for block_no, block in enumerate(blocks):

        x0, y0, x1, y1, text, block_id, block_type = block[:7]

        print({
            "page": page_no,
            "block_id": block_no,
            "bbox": [x0, y0, x1, y1],
            "text": text.strip()
        })