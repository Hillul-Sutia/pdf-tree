
import pymupdf
from pathlib import Path
import re


PDF_PATH = Path(
    r"E:\HILLUL\Project Associate - I\SDEP\Indigenous fermented foods of Northeast India Emerging opportunities in functional foods, microbiota-driven nutrition and safety perspectives.pdf"
)

OUTPUT_PATH = Path("paper_blocks.md")


# ------------------------------------------------------------
# BOLD DETECTION
# ------------------------------------------------------------

def is_bold(span):
    """
    Detect bold text using both PyMuPDF font flags and
    the actual font name.

    This is more reliable because some PDFs do not correctly
    expose the bold style through the flags alone.
    """

    flags = span.get("flags", 0)
    font_name = span.get("font", "")

    # PyMuPDF bold flag
    flag_bold = bool(flags & 16)

    # Font-name based detection
    font_lower = font_name.lower()

    name_bold = any(
        keyword in font_lower
        for keyword in [
            "bold",
            "black",
            "heavy",
            "semibold",
            "demibold",
        ]
    )

    return flag_bold or name_bold


# ------------------------------------------------------------
# MARKDOWN TEXT ESCAPING
# ------------------------------------------------------------

def escape_markdown_text(text):
    """
    Minimal escaping.

    Do NOT escape '*' because we need it for bold formatting.
    """

    return text.replace("\\", "\\\\")


# ------------------------------------------------------------
# RECONSTRUCT A BLOCK
# ------------------------------------------------------------

def reconstruct_block(block):
    """
    Reconstruct a PDF text block while preserving inline bold
    formatting.

    Example:

        This is normal and this is bold.

    becomes:

        This is normal and **this is bold**.
    """

    lines = []

    for line in block.get("lines", []):

        parts = []

        previous_span = None

        for span in line.get("spans", []):

            text = span.get("text", "")

            if not text:
                continue

            # ------------------------------------------------
            # Preserve spacing between spans
            # ------------------------------------------------

            if previous_span is not None:

                prev_bbox = previous_span.get("bbox", [0, 0, 0, 0])
                curr_bbox = span.get("bbox", [0, 0, 0, 0])

                previous_x1 = prev_bbox[2]
                current_x0 = curr_bbox[0]

                gap = current_x0 - previous_x1

                if (
                    gap > 1.5
                    and not text.startswith(
                        (" ", ".", ",", ";", ":", "!", "?", ")", "]", "}")
                    )
                ):
                    parts.append(" ")

            # ------------------------------------------------
            # Format span
            # ------------------------------------------------

            text = escape_markdown_text(text)

            if is_bold(span):

                # Avoid producing **** for empty/whitespace text
                stripped = text.strip()

                if stripped:

                    # Preserve leading/trailing whitespace
                    leading = text[: len(text) - len(text.lstrip())]
                    trailing = text[len(text.rstrip()):]

                    formatted = (
                        leading
                        + "**"
                        + stripped
                        + "**"
                        + trailing
                    )

                    parts.append(formatted)

                else:
                    parts.append(text)

            else:
                parts.append(text)

            previous_span = span

        line_text = "".join(parts)

        if line_text.strip():
            lines.append(line_text)

    return "\n".join(lines)


# ------------------------------------------------------------
# GET BLOCK TEXT WITHOUT MARKDOWN
# ------------------------------------------------------------

def get_plain_block_text(block):
    """
    Get plain text from a block.
    """

    lines = []

    for line in block.get("lines", []):

        line_text = ""

        for span in line.get("spans", []):

            line_text += span.get("text", "")

        if line_text.strip():
            lines.append(line_text.strip())

    return "\n".join(lines)


# ------------------------------------------------------------
# BLOCK STATISTICS
# ------------------------------------------------------------

def get_block_statistics(block):

    total_chars = 0
    bold_chars = 0

    for line in block.get("lines", []):

        for span in line.get("spans", []):

            text = span.get("text", "")

            if not text.strip():
                continue

            length = len(text.strip())

            total_chars += length

            if is_bold(span):
                bold_chars += length

    if total_chars == 0:
        return 0, 0, 0.0

    bold_ratio = bold_chars / total_chars

    return total_chars, bold_chars, bold_ratio


# ------------------------------------------------------------
# HEADING DETECTION
# ------------------------------------------------------------

def looks_like_heading(block):

    total_chars, bold_chars, bold_ratio = get_block_statistics(block)

    if total_chars == 0:
        return False

    # Predominantly bold
    if bold_ratio < 0.70:
        return False

    # Avoid treating long paragraphs as headings
    if total_chars > 200:
        return False

    plain_text = get_plain_block_text(block).strip()

    if not plain_text:
        return False

    # Avoid very long multi-word paragraphs
    if len(plain_text.split()) > 30:
        return False

    return True


# ------------------------------------------------------------
# HEADING LEVEL
# ------------------------------------------------------------

def determine_heading_level(block):

    """
    Determine a simple Markdown heading level based on
    font size.

    This is only a heuristic.
    """

    sizes = []

    for line in block.get("lines", []):

        for span in line.get("spans", []):

            if span.get("text", "").strip():

                sizes.append(span.get("size", 0))

    if not sizes:
        return 2

    max_size = max(sizes)

    if max_size >= 18:
        return 1

    elif max_size >= 15:
        return 2

    elif max_size >= 13:
        return 3

    else:
        return 4


# ------------------------------------------------------------
# PDF → MARKDOWN
# ------------------------------------------------------------

def pdf_to_markdown(pdf_path, output_path):

    doc = pymupdf.open(pdf_path)

    with output_path.open("w", encoding="utf-8") as md:

        for page_number, page in enumerate(doc, start=1):

            md.write(f"# Page {page_number}\n\n")

            page_dict = page.get_text("dict")

            # IMPORTANT:
            # This preserves the ORIGINAL PyMuPDF block index.
            for block_number, block in enumerate(
                page_dict.get("blocks", [])
            ):

                # Text blocks only
                if block.get("type") != 0:
                    continue

                text = reconstruct_block(block)

                if not text.strip():
                    continue

                bbox = block.get(
                    "bbox",
                    [0, 0, 0, 0]
                )

                x0, y0, x1, y1 = bbox

                # ------------------------------------------------
                # BLOCK IDENTIFIER
                # ------------------------------------------------

                md.write(
                    f"### [Page {page_number} | Block {block_number}]\n\n"
                )

                md.write(
                    f"<!-- bbox: "
                    f"{x0:.1f}, {y0:.1f}, "
                    f"{x1:.1f}, {y1:.1f} -->\n\n"
                )

                # ------------------------------------------------
                # HEADING
                # ------------------------------------------------

                if looks_like_heading(block):

                    plain_text = get_plain_block_text(block).strip()

                    level = determine_heading_level(block)

                    md.write(
                        f'{"#" * level} {plain_text}\n\n'
                    )

                # ------------------------------------------------
                # NORMAL PARAGRAPH / BLOCK
                # ------------------------------------------------

                else:

                    md.write(text)
                    md.write("\n\n")

    doc.close()

    print(f"Markdown written to: {output_path}")


if __name__ == "__main__":
    pdf_to_markdown(
        PDF_PATH,
        OUTPUT_PATH
    )