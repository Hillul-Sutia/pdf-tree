import fitz


def annotate_horizontal_lines(input_pdf, output_pdf):
    doc = fitz.open(input_pdf)

    for page_num, page in enumerate(doc):
        page_width = page.rect.width

        for drawing in page.get_drawings():
            for item in drawing["items"]:

                # "l" = line
                if item[0] != "l":
                    continue

                p1, p2 = item[1], item[2]

                # Check whether line is approximately horizontal
                if abs(p2.y - p1.y) > 2:
                    continue

                # Calculate line length
                line_length = abs(p2.x - p1.x)

                # Ignore very short lines
                if line_length < page_width * 0.20:
                    continue

                # Bounding box around line
                x0 = min(p1.x, p2.x)
                x1 = max(p1.x, p2.x)

                rect = fitz.Rect(
                    x0,
                    min(p1.y, p2.y) - 3,
                    x1,
                    max(p1.y, p2.y) + 3
                )

                # Draw rectangle around detected line
                page.draw_rect(
                    rect,
                    color=(1, 0, 0),
                    width=1
                )

                # Add label
                page.insert_text(
                    fitz.Point(x0, rect.y0 - 3),
                    "HORIZONTAL_LINE",
                    fontsize=7,
                    color=(1, 0, 0)
                )

    doc.save(output_pdf)
    doc.close()


annotate_horizontal_lines(
    r"E:\HILLUL\Project Associate - I\SDEP\pdf_tree\data\pdfs\Co-occurrence of antimicrobial resistance and virulence determinants in enterococci isolated from traditionally fermented fish products.pdf",
    "annotated.pdf"
)