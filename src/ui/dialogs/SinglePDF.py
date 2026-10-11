import os
import re
import sys 

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True

    class PDF(FPDF):
        """Custom PDF class to handle headers and footers."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.font_family_main = 'Arial' 

        def header(self):
            pass 

        def footer(self):
            self.set_y(-15)
            self.set_font(self.font_family_main, '', 8)
            self.cell(0, 10, 'Page ' + str(self.page_no()), 0, 0, 'C')

except Exception as e:
    print(f"\n❌ DEBUG INFO: Import failed. The specific error is: {e}")
    print(f"❌ DEBUG INFO: Python running this script is located at: {sys.executable}\n")
    FPDF_AVAILABLE = False
    FPDF = None 
    PDF = None

def strip_html_tags(text):
    if not text:
        return ""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def write_text_with_links(pdf, text, font_family, font_size=12, line_height=7):
    if not text: return

    # Split on paragraph breaks (double newlines)
    paragraphs = re.split(r'\n\n', text)

    for para_idx, paragraph in enumerate(paragraphs):
        if not paragraph.strip():
            # Empty paragraph -> blank line gap
            pdf.ln(line_height)
            continue

        # Within a paragraph, handle single newlines and inline URLs
        lines = paragraph.split('\n')
        for line_idx, line in enumerate(lines):
            parts = re.split(r'(https?://[^\s\]\)>]+)', line)
            pdf.set_font(font_family, '', font_size)
            for part in parts:
                if part.startswith('http://') or part.startswith('https://'):
                    pdf.set_text_color(0, 0, 255)
                    pdf.set_font(font_family, 'U', font_size)
                    pdf.write(line_height, part, part)
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font(font_family, '', font_size)
                else:
                    pdf.write(line_height, part)
            # Newline after each line within paragraph (except last)
            if line_idx < len(lines) - 1:
                pdf.ln(line_height)

        # Paragraph gap after each paragraph (except last)
        if para_idx < len(paragraphs) - 1:
            pdf.ln(line_height * 2)

def _setup_pdf_fonts(pdf, font_path, logger=print):
    """Helper to setup fonts for the PDF instance."""
    bold_font_path = ""
    default_font = 'Arial'
    
    if font_path:
        bold_font_path = font_path.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")

    try:
        if font_path and os.path.exists(font_path): 
            pdf.add_font('DejaVu', '', font_path, uni=True)
            default_font = 'DejaVu'
            if os.path.exists(bold_font_path): 
                pdf.add_font('DejaVu', 'B', bold_font_path, uni=True)
            else:
                pdf.add_font('DejaVu', 'B', font_path, uni=True)
    except Exception as font_error:
        logger(f"   ⚠️ Could not load DejaVu font: {font_error}. Falling back to Arial.")
        default_font = 'Arial'
    
    pdf.font_family_main = default_font
    return default_font

def add_metadata_page(pdf, post, font_family):
    """Adds a dedicated metadata page to the PDF with clickable links."""
    pdf.add_page()
    pdf.set_font(font_family, 'B', 16)
    pdf.multi_cell(w=0, h=10, txt=post.get('title', 'Untitled Post'), align='C')
    pdf.ln(10)
    pdf.set_font(font_family, '', 11)
    
    def add_info_row(label, value, link_url=None):
        if not value: return
        
        pdf.set_font(font_family, 'B', 11)
        pdf.write(8, f"{label}: ")
        
        if label == "Service" and value != "Unknown" and value != "kemono":
            labels = value.split(', ')
            for lbl in labels:
                lbl_lower = lbl.lower()
                if 'patreon' in lbl_lower:
                    pdf.set_fill_color(249, 104, 84)
                elif 'request' in lbl_lower:
                    pdf.set_fill_color(0, 123, 255)
                elif 'onlyfans' in lbl_lower:
                    pdf.set_fill_color(0, 175, 240)
                elif 'mega' in lbl_lower:
                    pdf.set_fill_color(217, 39, 46)
                elif 'fansly' in lbl_lower:
                    pdf.set_fill_color(46, 164, 255)
                else:
                    pdf.set_fill_color(100, 100, 100)
                
                pdf.set_text_color(255, 255, 255)
                w = pdf.get_string_width(" " + lbl + " ")
                pdf.cell(w, 8, " " + lbl + " ", 0, 0, 'C', fill=True)
                pdf.set_text_color(0, 0, 0)
                pdf.set_x(pdf.get_x() + 2)
            pdf.ln(8)
            return
            
        if link_url:
            pdf.set_text_color(0, 0, 255)
            pdf.set_font(font_family, 'U', 11) 
            
            pdf.write(8, str(value), link_url)
            pdf.ln(8)
            
            pdf.set_text_color(0, 0, 0)
            pdf.set_font(font_family, '', 11)
        else:
            pdf.set_font(font_family, '', 11)
            pdf.multi_cell(w=0, h=8, txt=str(value))
            
        pdf.ln(2)

    date_str = post.get('published') or post.get('added') or 'Unknown'
    add_info_row("Date Uploaded", date_str)
    
    creator = post.get('creator_name') or post.get('user') or 'Unknown'
    add_info_row("Creator", creator)
    
    add_info_row("Service", post.get('service', 'Unknown'))
    
    link = post.get('original_link')
    if not link and post.get('service') and post.get('user') and post.get('id'):
        link = f"https://kemono.su/{post['service']}/user/{post['user']}/post/{post['id']}"
    
    add_info_row("Original Link", link, link_url=link)
    
    tags = post.get('tags')
    if tags:
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        add_info_row("Tags", tags_str)

    pdf.ln(10)
    pdf.cell(0, 0, border='T') 
    pdf.ln(10)

def render_poll_in_pdf(pdf, poll_data, font_family):
    """Renders a visual representation of a poll in the PDF,
    styled to resemble the Kemono website's poll card layout."""
    if not poll_data:
        return

    pdf.ln(5)

    # ── Section header: "Poll" ──────────────────────────────────────────────
    pdf.set_font(font_family, 'B', 13)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "Poll", ln=True)
    pdf.ln(1)

    poll_title = poll_data.get('title', 'Poll')
    choices = poll_data.get('choices', [])
    if not choices:
        pdf.set_font(font_family, 'I', 11)
        pdf.multi_cell(w=0, h=7, txt="No choices available.")
        pdf.ln(5)
        return

    total_votes = sum(c.get('votes', 0) for c in choices)
    created_at = poll_data.get('created_at', '')
    closes_at  = poll_data.get('closes_at', '')

    # Card dimensions
    left_margin   = pdf.get_x()
    card_width    = 160          # mm – roughly A4 usable width
    row_h         = 8           # row height mm
    text_col_w    = card_width - 28  # space for choice text
    vote_col_w    = 28          # space for vote count

    # ── Poll title bar ──────────────────────────────────────────────────────
    pdf.set_fill_color(245, 245, 245)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(font_family, 'B', 11)
    pdf.cell(card_width, row_h + 2, f"  {poll_title}", border=1, ln=True, fill=True)

    # ── Each choice row ─────────────────────────────────────────────────────
    for idx, choice in enumerate(choices):
        text  = choice.get('text', 'Unknown')
        votes = choice.get('votes', 0)
        percentage = (votes / total_votes * 100) if total_votes > 0 else 0

        # Alternate row shading (very subtle)
        if idx % 2 == 0:
            pdf.set_fill_color(255, 255, 255)
        else:
            pdf.set_fill_color(250, 250, 252)

        row_y = pdf.get_y()

        # Choice text cell (left-aligned, with left padding)
        pdf.set_font(font_family, '', 10)
        pdf.set_draw_color(200, 200, 200)
        # Draw progress bar background across the full text column
        bar_bg_h = row_h - 2
        pdf.set_fill_color(240, 240, 240)
        pdf.rect(x=left_margin, y=row_y, w=card_width, h=row_h, style='FD')

        # Progress fill
        fill_w = (percentage / 100) * (text_col_w - 4)
        if fill_w > 0:
            pdf.set_fill_color(180, 210, 255)   # light blue fill
            pdf.rect(x=left_margin + 2, y=row_y + 1, w=fill_w, h=bar_bg_h, style='F')

        # Text over the bar
        pdf.set_xy(left_margin + 2, row_y)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(font_family, '', 10)
        # Truncate text if too long
        max_chars = int(text_col_w / 2.1)
        display_text = text if len(text) <= max_chars else text[:max_chars - 1] + "…"
        pdf.cell(text_col_w, row_h, display_text, border=0)

        # Vote count cell (right side)
        pdf.set_xy(left_margin + text_col_w, row_y)
        pdf.set_font(font_family, 'B', 10)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(vote_col_w, row_h, str(votes), border='L', align='R')

        pdf.ln(row_h)

    # ── Footer: date range & total votes ────────────────────────────────────
    pdf.set_fill_color(245, 245, 245)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_text_color(120, 120, 120)
    pdf.set_font(font_family, '', 9)

    # Format dates: strip time if present
    def _short_date(dt_str):
        return dt_str[:10] if dt_str and len(dt_str) >= 10 else dt_str

    footer_parts = []
    if created_at:
        footer_parts.append(_short_date(created_at))
    if closes_at:
        footer_parts.append(_short_date(closes_at))
    date_range = "—".join(footer_parts) if footer_parts else ""
    footer_txt = f"  {date_range}  |  {total_votes} votes" if date_range else f"  {total_votes} votes"

    pdf.cell(card_width, 7, footer_txt, border=1, ln=True, fill=True)

    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(5)

def create_individual_pdf(post_data, output_filename, font_path, add_info_page=False, add_comments=False, logger=print):
    """
    Creates a PDF for a single post.
    Supports optional metadata page and appending comments.
    """
    if not FPDF_AVAILABLE:
        logger("❌ PDF Creation failed: 'fpdf2' library not installed.")
        return False

    pdf = PDF()
    font_family = _setup_pdf_fonts(pdf, font_path, logger)
    
    if add_info_page:

        add_metadata_page(pdf, post_data, font_family)

    else:
        pdf.add_page()

    if not add_info_page:
        pdf.set_font(font_family, 'B', 16)
        pdf.multi_cell(w=0, h=10, txt=post_data.get('title', 'Untitled Post'), align='L')
        pdf.ln(5)

    content_text = post_data.get('content_text_for_pdf')
    comments_list = post_data.get('comments_list_for_pdf')

    if content_text:
        write_text_with_links(pdf, content_text, font_family, font_size=12, line_height=7)
        pdf.ln(10)

    if post_data.get('poll'):
        render_poll_in_pdf(pdf, post_data.get('poll'), font_family)

    if comments_list and (add_comments or not content_text):
        if add_comments and content_text:
             pdf.add_page()
             pdf.set_font(font_family, 'B', 14)
             pdf.cell(0, 10, "Comments", ln=True)
             pdf.ln(5)

        for i, comment in enumerate(comments_list):
            user = comment.get('commenter_name', 'Unknown User')
            timestamp = comment.get('published', 'No Date')
            body = strip_html_tags(comment.get('content', ''))

            pdf.set_font(font_family, '', 10)
            pdf.write(8, "Comment by: ")
            pdf.set_font(font_family, 'B', 10)
            pdf.write(8, str(user))
            
            pdf.set_font(font_family, '', 10)
            pdf.write(8, f" on {timestamp}")
            pdf.ln(10)

            pdf.set_font(font_family, '', 11)
            pdf.multi_cell(w=0, h=7, txt=body)
            
            if i < len(comments_list) - 1:
                pdf.ln(3)
                pdf.cell(w=0, h=0, border='T')
                pdf.ln(3)
    
    try:
        pdf.output(output_filename)
        return True
    except Exception as e:
        logger(f"❌ Error saving PDF '{os.path.basename(output_filename)}': {e}")
        return False

def create_single_pdf_from_content(posts_data, output_filename, font_path, add_info_page=False, continuous=False, logger=print):
    """
    Creates a single, continuous PDF from multiple posts.
    """
    if not FPDF_AVAILABLE:
        logger("❌ PDF Creation failed: 'fpdf2' library is not installed.")
        return False

    if not posts_data:
        logger("   No text content was collected to create a PDF.")
        return False

    pdf = PDF()
    font_family = _setup_pdf_fonts(pdf, font_path, logger)
    
    logger(f"   Starting continuous PDF creation with content from {len(posts_data)} posts...")

    for i, post in enumerate(posts_data):
        is_first = (i == 0)
        
        if continuous and not is_first:
            pdf.ln(5)
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(5)
            
            # Sub-header for comment
            author = post.get('creator_name', 'Unknown User')
            date = post.get('published', '')
            pdf.set_font(font_family, 'B', 12)
            pdf.write(8, str(author))
            if date:
                pdf.set_font(font_family, '', 10)
                pdf.write(8, f" on {date}")
            pdf.ln(8)
            
            content_text = post.get('content_text_for_pdf') or post.get('content', '')
            if content_text:
                write_text_with_links(pdf, content_text, font_family, font_size=11, line_height=7)
                pdf.ln(5)
                
            if post.get('poll'):
                render_poll_in_pdf(pdf, post.get('poll'), font_family)
                
            continue

        if add_info_page:
            add_metadata_page(pdf, post, font_family)
        else:
            pdf.add_page()

        if not add_info_page:
            pdf.set_font(font_family, 'B', 16)
            pdf.multi_cell(w=0, h=10, txt=post.get('title', 'Untitled Post'), align='L')
            pdf.ln(5)
            
        content_text = post.get('content_text_for_pdf') or post.get('content', '')
        if content_text:
            write_text_with_links(pdf, content_text, font_family, font_size=12, line_height=7)
            pdf.ln(7)

        if post.get('poll'):
            render_poll_in_pdf(pdf, post.get('poll'), font_family)

        if 'comments' in post and post['comments']:
            comments_list = post['comments']
            for comment_index, comment in enumerate(comments_list):
                user = comment.get('commenter_name', 'Unknown User')
                timestamp = comment.get('published', 'No Date')
                body = strip_html_tags(comment.get('content', ''))

                pdf.set_font(font_family, '', 10)
                pdf.write(8, "Comment by: ")
                if user is not None:
                    pdf.set_font(font_family, 'B', 10)
                    pdf.write(8, str(user))
                
                pdf.set_font(font_family, '', 10)
                pdf.write(8, f" on {timestamp}")
                pdf.ln(10)

                pdf.set_font(font_family, '', 11)
                pdf.multi_cell(w=0, h=7, txt=body)
                
                if comment_index < len(comments_list) - 1:
                    pdf.ln(3)
                    pdf.cell(w=0, h=0, border='T')
                    pdf.ln(3)
    
    try:
        output_dir = os.path.dirname(output_filename)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)        
        pdf.output(output_filename)
        logger(f"✅ Successfully created single PDF: '{os.path.basename(output_filename)}'")
        return True
    except Exception as e:
        logger(f"❌ A critical error occurred while saving the final PDF: {e}")
        return False