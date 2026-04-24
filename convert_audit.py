import os
import re
from fpdf import FPDF

# Configuration
INPUT_FILE = "FULL_CODE_MASTER_AUDIT.md"
OUTPUT_FILE = "FULL_CODE_MASTER_AUDIT.pdf"
LOGO_FILE = "anunnaki.jpeg"
PLATFORM_NAME = "Anunnaki World Signals"

# Theme Colors (Premium Digital Dark Mode)
BG_COLOR = (10, 11, 14)        # Deep space gray/black
TEXT_COLOR = (201, 209, 217)    # Ghostly white/gray
ACCENT_COLOR = (58, 167, 87)    # High-conviction green
HEADER_COLOR = (240, 246, 252)  # Brightest white
CODE_BG = (22, 27, 34)         # Slightly lighter gray for code blocks

class AuditPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("helvetica", "I", 8)
            self.set_text_color(*ACCENT_COLOR)
            self.cell(0, 10, f"{PLATFORM_NAME} | Master Architectural Audit", border=0, align="R")
            self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(*TEXT_COLOR)
        self.cell(0, 10, f"Page {self.page_no()}", border=0, align="C")

def clean_text(text):
    # Mapping common problematic unicode characters to ASCII/Latin-1 equivalents
    mapping = {
        "\u2014": "-", # em dash
        "\u2013": "-", # en dash
        "\u201c": '"', # smart open quote
        "\u201d": '"', # smart close quote
        "\u2018": "'", # smart open single quote
        "\u2019": "'", # smart close single quote
        "\u2022": "*", # bullet
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text.encode('latin-1', 'replace').decode('latin-1')

def generate_pdf():
    pdf = AuditPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Effective width calculation
    eff_w = pdf.w - 2 * 10 

    # --- COVER PAGE ---
    pdf.add_page()
    pdf.set_fill_color(*BG_COLOR)
    pdf.rect(0, 0, 210, 297, "F")
    
    # Logo
    if os.path.exists(LOGO_FILE):
        pdf.image(LOGO_FILE, x=55, y=40, w=100)
    
    pdf.set_y(150)
    pdf.set_font("helvetica", "B", 26)
    pdf.set_text_color(*HEADER_COLOR)
    pdf.cell(0, 15, clean_text(PLATFORM_NAME), ln=True, align="C")
    
    pdf.set_font("helvetica", "B", 18)
    pdf.set_text_color(*ACCENT_COLOR)
    pdf.cell(0, 15, "Definitive Architectural Audit", ln=True, align="C")
    
    pdf.set_y(240)
    pdf.set_font("helvetica", "", 12)
    pdf.set_text_color(*TEXT_COLOR)
    pdf.cell(0, 10, "400-Layer Systemic Deconstruction", ln=True, align="C")
    pdf.cell(0, 10, "STRICTLY CONFIDENTIAL | INTERNAL OPS", ln=True, align="C")

    # --- TABLE OF CONTENTS ---
    pdf.add_page()
    pdf.set_fill_color(*BG_COLOR)
    pdf.rect(0, 0, 210, 297, "F")
    
    pdf.set_font("helvetica", "B", 20)
    pdf.set_text_color(*ACCENT_COLOR)
    pdf.cell(0, 20, "Table of Contents", ln=True)
    
    toc = []
    with open(INPUT_FILE, "r") as f:
        lines = f.readlines()
        for line in lines:
            if line.startswith("## LAYER "):
                # Extract layer number and title
                match = re.search(r"## LAYER (\d+): (.*)", line)
                if match:
                    toc.append(f"L{match.group(1)}: {match.group(2)}")
                else:
                    toc.append(line.strip("# ").strip())

    pdf.set_font("helvetica", "", 6) # Tiny font for massive TOC
    pdf.set_text_color(*TEXT_COLOR)
    
    # Multi-column TOC (3 columns)
    col_width = (pdf.w - 30) / 3
    start_y = pdf.get_y()
    current_col = 0
    pdf.set_left_margin(10)
    
    for item in toc:
        if pdf.get_y() > 275:
            if current_col < 2:
                current_col += 1
                pdf.set_xy(10 + (current_col * (col_width + 5)), start_y)
            else:
                pdf.add_page()
                pdf.set_fill_color(*BG_COLOR)
                pdf.rect(0, 0, 210, 297, "F")
                current_col = 0
                pdf.set_xy(10, 20)
                start_y = 20
        
        pdf.cell(col_width, 3.5, clean_text(item[:45]), ln=True) # Truncate long lines to prevent wrap failures

    # --- CONTENT PAGES ---
    pdf.add_page()
    pdf.set_fill_color(*BG_COLOR)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_left_margin(10)
    pdf.set_y(20)

    for line in lines:
        line = clean_text(line.strip("\n"))
        if not line.strip():
            pdf.ln(2)
            continue
            
        if pdf.get_y() > 270:
            pdf.add_page()
            pdf.set_fill_color(*BG_COLOR)
            pdf.rect(0, 0, 210, 297, "F")
            pdf.set_y(20)

        if line.startswith("# "):
            pdf.ln(10)
            pdf.set_font("helvetica", "B", 18)
            pdf.set_text_color(*HEADER_COLOR)
            pdf.multi_cell(eff_w, 10, line.lstrip("# ").strip())
        elif line.startswith("## "):
            pdf.ln(5)
            pdf.set_font("helvetica", "B", 14)
            pdf.set_text_color(*ACCENT_COLOR)
            pdf.multi_cell(eff_w, 8, line.lstrip("# ").strip())
        elif line.startswith("### "):
            pdf.set_font("helvetica", "B", 12)
            pdf.set_text_color(*HEADER_COLOR)
            pdf.multi_cell(eff_w, 7, line.lstrip("# ").strip())
        elif line.startswith("- "):
            pdf.set_font("helvetica", "", 10)
            pdf.set_text_color(*TEXT_COLOR)
            pdf.set_x(15)
            pdf.multi_cell(eff_w - 5, 6, f"* {line.lstrip('- ').strip()}")
        elif line.startswith("---"):
            pdf.set_draw_color(*ACCENT_COLOR)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(5)
        else:
            # Code blocks or standard text
            if "`" in line:
                pdf.set_font("courier", "", 9)
                pdf.set_text_color(*ACCENT_COLOR)
            else:
                pdf.set_font("helvetica", "", 10)
                pdf.set_text_color(*TEXT_COLOR)
            
            pdf.multi_cell(eff_w, 6, line)

    pdf.output(OUTPUT_FILE)
    print(f"Success: {OUTPUT_FILE} generated.")

if __name__ == "__main__":
    generate_pdf()
