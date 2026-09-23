from pathlib import Path
import pymupdf


def visualize_pymupdf_blocks(input_dir, output_dir):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process all PDFs in the input directory
    pdf_files = input_dir.glob("*.pdf")

    for pdf_path in pdf_files:

        # Output has the same filename
        output_path = output_dir / pdf_path.name

        print(f"Processing: {pdf_path.name}")

        doc = pymupdf.open(pdf_path)

        for page_number, page in enumerate(doc):

            blocks = page.get_text("blocks")

            for block_no, block in enumerate(blocks):

                x0, y0, x1, y1, text, *_ = block

                rect = pymupdf.Rect(x0, y0, x1, y1)

                # Draw rectangle around block
                page.draw_rect(
                    rect,
                    color=(1, 0, 0),
                    width=1,
                )

                # Block label
                label = f"B{block_no}"

                label_rect = pymupdf.Rect(
                    x0,
                    max(0, y0 - 12),
                    min(page.rect.width, x0 + 350),
                    y0,
                )

                page.insert_textbox(
                    label_rect,
                    label,
                    fontsize=6,
                    color=(0, 0, 0),
                )

        doc.save(output_path)
        doc.close()

        print(f"Saved: {output_path}")


if __name__ == "__main__":

    input_directory = "data/pdfs"
    output_directory = "data/visualized_pdfs"

    visualize_pymupdf_blocks(
        input_directory,
        output_directory,
    )