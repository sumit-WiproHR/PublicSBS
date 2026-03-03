import streamlit as st
import pandas as pd
import os
import datetime
import uuid
import io
import re
from dataclasses import dataclass
from typing import List, Dict
from pypdf import PdfReader
import docx

# --- 1. CONFIGURATION & UI SETUP ---
st.set_page_config(page_title="SxS DD Generator (TUPE/ARD)", layout="wide")
st.title("SxS DD Generator (TUPE/ARD)")
st.markdown("Upload due diligence documentation to generate an automated Side-by-Side (SxS) comparison for TUPE/ARD requirements.")

with st.expander("Deal Information", expanded=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        deal_name = st.text_input("Deal Name", placeholder="e.g., Project Phoenix")
    with col2:
        acquired_entity = st.text_input("Acquired Entity Name", placeholder="e.g., TargetCo Ltd")
    with col3:
        country = st.text_input("Country", placeholder="e.g., UK, Germany")

with st.expander("Document Uploads", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        acquired_files = st.file_uploader(f"Upload Acquired Documents", accept_multiple_files=True, key="acquired")
    with col2:
        wipro_files = st.file_uploader("Upload Wipro Documents", accept_multiple_files=True, key="wipro")

# --- 2. FILE & TEXT MANAGEMENT ---
def save_uploaded_files(files, run_folder, subfolder):
    target_dir = os.path.join(run_folder, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    for file in files:
        with open(os.path.join(target_dir, file.name), "wb") as f:
            f.write(file.getbuffer())
    return [file.name for file in files]

def parse_document(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    parsed_content = []
    try:
        if ext == '.pdf':
            reader = PdfReader(filepath)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    parsed_content.append({"page_section": f"Page {i + 1}", "text": " ".join(text.split())})
        elif ext in ['.docx', '.doc']:
            doc = docx.Document(filepath)
            current_section = []
            section_counter = 1
            for para in doc.paragraphs:
                if para.text.strip():
                    current_section.append(para.text.strip())
                if len(current_section) >= 10:
                    parsed_content.append({"page_section": f"Section {section_counter}", "text": " ".join(current_section)})
                    current_section = []
                    section_counter += 1
            if current_section:
                parsed_content.append({"page_section": f"Section {section_counter}", "text": " ".join(current_section)})
    except Exception as e:
        parsed_content.append({"page_section": "Error", "text": f"Failed to parse document: {str(e)}"})
    return parsed_content

# --- 3. DATA STRUCTURES: EVIDENCE LEDGER ---
@dataclass
class EvidenceRecord:
    evidence_id: str
    doc_name: str
    page_section: str
    verbatim_quote: str

class EvidenceLedger:
    def __init__(self):
        self.records: Dict[str, EvidenceRecord] = {}

    def add_evidence(self, doc_name: str, page_section: str, verbatim_quote: str) -> str:
        if not doc_name or not page_section or not verbatim_quote:
            return None
        ev_id = f"EV-{len(self.records) + 1:03d}"
        self.records[ev_id] = EvidenceRecord(ev_id, doc_name, page_section, verbatim_quote)
        return ev_id

    def to_dataframe(self) -> pd.DataFrame:
        data = [{"Evidence ID": rec.evidence_id, "Source Document": rec.doc_name, "Page/Section": rec.page_section, "Verbatim Quote": rec.verbatim_quote} for rec in self.records.values()]
        return pd.DataFrame(data)

@dataclass
class ExtractedField:
    value: str
    evidence_ids: List[str]

    def to_cell(self) -> str:
        val = str(self.value).strip() if self.value else ""
        if not val or val.lower() == "unknown":
            return "Unknown [FLAGGED FOR REVIEW: Missing Value]"
        valid_refs = [eid for eid in self.evidence_ids if eid]
        if not valid_refs:
            return f"{val} [FLAGGED FOR REVIEW: Missing Evidence]"
        return f"{val} [Refs: {', '.join(valid_refs)}]"

class DeterministicComparator:
    @staticmethod
    def compare_benefits(acq_val: str, wip_val: str, category: str) -> str:
        def extract_num(text):
            match = re.search(r'\d+(\.\d+)?', str(text))
            return float(match.group()) if match else None
        acq_num, wip_num = extract_num(acq_val), extract_num(wip_val)
        if acq_num is None or wip_num is None:
            return "Unknown [Requires Manual Review]"
        if category.lower() in ["annual leave", "bonus percentage", "severance weeks"]:
            if wip_num > acq_num: return "Better"
            if wip_num < acq_num: return "Worse"
            return "Neutral"
        elif category.lower() in ["working hours", "probation months"]:
            if wip_num < acq_num: return "Better"
            if wip_num > acq_num: return "Worse"
            return "Neutral"
        return "Unknown [Rule Not Defined]"

# --- 4. EXTRACTION PIPELINE (MOCK LLM) ---
def run_extraction_pipeline(deal, entity, country, acq_filenames, wip_filenames, run_folder):
    ledger = EvidenceLedger()
    
    # Parse documents (Data is ready for future LLM integration)
    acq_texts, wip_texts = {}, {}
    for filename in acq_filenames:
        acq_texts[filename] = parse_document(os.path.join(run_folder, "Acquired_Docs", filename))
    for filename in wip_filenames:
        wip_texts[filename] = parse_document(os.path.join(run_folder, "Wipro_Docs", filename))
        
    # Mock Sheets Construction
    sources_data = [{"Document Name": f, "Set": "Acquired Entity", "Upload Date": datetime.date.today()} for f in acq_filenames] + \
                   [{"Document Name": f, "Set": "Wipro", "Upload Date": datetime.date.today()} for f in wip_filenames]

    acq_doc = acq_filenames[0] if acq_filenames else "Acq_Handbook.pdf"
    wip_doc = wip_filenames[0] if wip_filenames else "Wipro_Handbook.pdf"

    acq_leave = ExtractedField("28 days", [ledger.add_evidence(acq_doc, "Page 12", "Employees receive 28 days paid leave.")])
    wip_leave = ExtractedField("25 days", [ledger.add_evidence(wip_doc, "Section 4.1", "Standard holiday entitlement is 25 days.")])
    acq_bonus = ExtractedField("10% Target", []) # Missing evidence on purpose
    wip_bonus = ExtractedField("Unknown", [])

    comparator = DeterministicComparator()
    benefits_data = [
        {"Benefit Category": "Annual Leave", "Acquired Entity Provision": acq_leave.to_cell(), "Wipro Provision": wip_leave.to_cell(), "Comparison Result": comparator.compare_benefits(acq_leave.value, wip_leave.value, "Annual Leave")},
        {"Benefit Category": "Bonus Percentage", "Acquired Entity Provision": acq_bonus.to_cell(), "Wipro Provision": wip_bonus.to_cell(), "Comparison Result": comparator.compare_benefits(acq_bonus.value, wip_bonus.value, "Bonus Percentage")}
    ]

    return {
        "Sources": pd.DataFrame(sources_data),
        "Benefits_SxS": pd.DataFrame(benefits_data),
        "Banding_Mapping": pd.DataFrame([{"Mapping Data": "Mock mapping pending LLM integration"}]),
        "Contractual_Risks": pd.DataFrame([{"Risk Data": "Mock risk pending LLM integration"}]),
        "Comments_Synthesis": pd.DataFrame([{"Synthesis Data": "Mock synthesis pending LLM integration"}]),
        "Evidence_Ledger": ledger.to_dataframe()
    }

# --- 5. EXCEL GENERATOR ---
def generate_excel(dataframes_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        format_flag = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
        format_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top'})
        
        for sheet_name, df in dataframes_dict.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            
            for row_idx, row in enumerate(df.values):
                for col_idx, cell_value in enumerate(row):
                    cell_str = str(cell_value)
                    if "FLAGGED FOR REVIEW" in cell_str or cell_str == "Unknown":
                        worksheet.write(row_idx + 1, col_idx, cell_str, format_flag)
                    else:
                        worksheet.write(row_idx + 1, col_idx, cell_str, format_wrap)
                        
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 60))
    return output.getvalue()

# --- 6. MAIN EXECUTION ---
if st.button("Generate Side-by-Side Excel", type="primary"):
    if not deal_name or not acquired_entity or not country:
        st.error("⚠️ Please fill in the Deal Name, Acquired Entity Name, and Country before proceeding.")
    elif not acquired_files or not wipro_files:
        st.error("⚠️ Please upload at least one document for both the Acquired entity and Wipro.")
    else:
        with st.spinner("Initializing run folder, processing documents, and generating extraction..."):
            run_id = str(uuid.uuid4())[:8]
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            run_folder = os.path.join("runs", f"run_{timestamp}_{run_id}")
            
            acq_names = save_uploaded_files(acquired_files, run_folder, "Acquired_Docs")
            wip_names = save_uploaded_files(wipro_files, run_folder, "Wipro_Docs")
            
            extracted_dfs = run_extraction_pipeline(deal_name, acquired_entity, country, acq_names, wip_names, run_folder)
            excel_data = generate_excel(extracted_dfs)
            
            st.success(f"✅ Analysis complete! Run folder created at: `{run_folder}`")
            st.download_button(
                label="📥 Download SxS Due Diligence Report (.xlsx)",
                data=excel_data,
                file_name=f"SxS_DD_{deal_name}_{country}_{timestamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )