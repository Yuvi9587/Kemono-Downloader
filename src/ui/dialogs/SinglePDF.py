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
    parts = re.split(r'(https?://[^\s\]\)\>]+)', text)
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