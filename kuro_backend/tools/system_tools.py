"""
Kuro AI V4.0 - System Tools for LangGraph ToolNode
================================================================================
Tool Definitions using LangChain @tool decorator for:
- Excel Report Generation
- File Management (sandboxed to /home/kuro/exports/)
- Report Templating (Markdown/PDF)
"""
import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ============================================
# SECURITY: SANDBOX CONFIGURATION
# ============================================

EXPORTS_DIR = "/home/kuro/exports"
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".md", ".txt", ".pdf", ".csv", ".json"}
MAX_FILE_SIZE_MB = 50

def validate_path(filepath: str) -> tuple[bool, str]:
    """
    Validate that a file path is within the allowed exports directory.
    Returns (is_valid, error_message).
    """
    try:
        # Resolve to absolute path
        resolved = Path(filepath).resolve()
        exports_resolved = Path(EXPORTS_DIR).resolve()
        
        # Check if path is within exports directory
        if not str(resolved).startswith(str(exports_resolved)):
            return False, f"Path traversal detected: {filepath} is outside {EXPORTS_DIR}"
        
        # Check extension
        ext = resolved.suffix.lower()
        if ext and ext not in ALLOWED_EXTENSIONS:
            return False, f"File extension {ext} not allowed. Allowed: {ALLOWED_EXTENSIONS}"
        
        # Check file size if exists
        if resolved.exists():
            size_mb = resolved.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                return False, f"File size {size_mb:.1f}MB exceeds limit of {MAX_FILE_SIZE_MB}MB"
        
        return True, ""
    except Exception as e:
        return False, f"Path validation error: {str(e)}"


def ensure_exports_dir():
    """Create exports directory if it doesn't exist."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    return EXPORTS_DIR


# ============================================
# TOOL: EXCEL GENERATOR
# ============================================

@tool
def generate_excel_report(
    data: str,
    filename: str,
    sheet_name: str = "Report",
    include_timestamp: bool = True
) -> str:
    """
    Generate an Excel (.xlsx) file from JSON data.
    
    Args:
        data: JSON string containing the data to write. Can be:
              - A list of dicts (each dict becomes a row)
              - A dict with "headers" and "rows" keys
              - A simple dict (will be converted to single-row table)
        filename: Name for the output file (will be saved to /home/kuro/exports/)
        sheet_name: Name of the Excel sheet (default: "Report")
        include_timestamp: Whether to add a timestamp column (default: True)
    
    Returns:
        Success message with file path, or error description.
    
    Example:
        generate_excel_report(
            data='[{"Finding": "Risk A", "Severity": "High"}, {"Finding": "Risk B", "Severity": "Medium"}]',
            filename="audit_findings.xlsx",
            sheet_name="Findings"
        )
    """
    try:
        import pandas as pd
        
        # Validate filename
        if not filename.endswith(('.xlsx', '.xls')):
            filename = f"{filename}.xlsx"
        
        # Security validation
        filepath = os.path.join(EXPORTS_DIR, filename)
        is_valid, error_msg = validate_path(filepath)
        if not is_valid:
            return f"ERROR: {error_msg}"
        
        # Ensure exports directory exists
        ensure_exports_dir()
        
        # Parse JSON data
        try:
            parsed_data = json.loads(data)
        except json.JSONDecodeError as e:
            return f"ERROR: Invalid JSON data: {str(e)}"
        
        # Convert to DataFrame
        if isinstance(parsed_data, list):
            df = pd.DataFrame(parsed_data)
        elif isinstance(parsed_data, dict):
            if "headers" in parsed_data and "rows" in parsed_data:
                df = pd.DataFrame(parsed_data["rows"], columns=parsed_data["headers"])
            else:
                df = pd.DataFrame([parsed_data])
        else:
            return "ERROR: Data must be a JSON array of objects or a structured object"
        
        if df.empty:
            return "ERROR: No data to write to Excel"
        
        # Add timestamp column if requested
        if include_timestamp:
            df["Generated At"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Write to Excel
        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Auto-adjust column widths
            worksheet = writer.sheets[sheet_name]
            for idx, col in enumerate(df.columns):
                max_length = max(
                    df[col].astype(str).str.len().max(),
                    len(str(col))
                ) + 2
                adjusted_width = min(max_length, 50)
                worksheet.column_dimensions[chr(65 + idx)].width = adjusted_width
        
        file_size = os.path.getsize(filepath) / 1024
        logger.info(f"[TOOL:EXCEL] Generated {filepath} ({file_size:.1f}KB)")
        
        return f"SUCCESS: Excel file created at {filepath} ({len(df)} rows, {file_size:.1f}KB)"
        
    except ImportError:
        return "ERROR: pandas and openpyxl are required. Install with: pip install pandas openpyxl"
    except Exception as e:
        logger.error(f"[TOOL:EXCEL] Failed: {e}")
        return f"ERROR: Failed to generate Excel: {str(e)}"


# ============================================
# TOOL: FILE MANAGER
# ============================================

@tool
def manage_files(
    action: str,
    filename: Optional[str] = None,
    content: Optional[str] = None,
    list_dir: str = "/"
) -> str:
    """
    Manage files in the exports directory (/home/kuro/exports/).
    
    Args:
        action: One of: "read", "write", "list", "delete", "info"
        filename: Target filename (required for read/write/delete/info)
        content: File content (required for write action)
        list_dir: Subdirectory to list (default: root exports dir)
    
    Returns:
        Operation result with file content, listing, or status.
    
    Examples:
        manage_files(action="list")
        manage_files(action="read", filename="report.md")
        manage_files(action="write", filename="notes.txt", content="Hello World")
        manage_files(action="delete", filename="old_report.xlsx")
        manage_files(action="info", filename="report.xlsx")
    """
    try:
        ensure_exports_dir()
        action = action.lower()
        
        if action == "list":
            # List files in directory
            target_dir = os.path.join(EXPORTS_DIR, list_dir.lstrip("/"))
            is_valid, error_msg = validate_path(target_dir)
            if not is_valid:
                return f"ERROR: {error_msg}"
            
            if not os.path.exists(target_dir):
                return f"ERROR: Directory {list_dir} does not exist"
            
            files = []
            for f in os.listdir(target_dir):
                fpath = os.path.join(target_dir, f)
                stat = os.stat(fpath)
                size_kb = stat.st_size / 1024
                modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                files.append({
                    "name": f,
                    "size_kb": round(size_kb, 1),
                    "modified": modified,
                    "type": "directory" if os.path.isdir(fpath) else "file"
                })
            
            if not files:
                return f"Directory {list_dir} is empty"
            
            result = f"Files in {list_dir}:\n"
            for f in files:
                icon = "📁" if f["type"] == "directory" else "📄"
                result += f"  {icon} {f['name']} ({f['size_kb']}KB, modified {f['modified']})\n"
            
            return result
        
        elif action == "read":
            if not filename:
                return "ERROR: filename required for read action"
            
            filepath = os.path.join(EXPORTS_DIR, filename)
            is_valid, error_msg = validate_path(filepath)
            if not is_valid:
                return f"ERROR: {error_msg}"
            
            if not os.path.exists(filepath):
                return f"ERROR: File {filename} does not exist"
            
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return f"Content of {filename}:\n\n{content[:5000]}"  # Limit output
        
        elif action == "write":
            if not filename:
                return "ERROR: filename required for write action"
            if content is None:
                return "ERROR: content required for write action"
            
            filepath = os.path.join(EXPORTS_DIR, filename)
            is_valid, error_msg = validate_path(filepath)
            if not is_valid:
                return f"ERROR: {error_msg}"
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            size_kb = len(content.encode('utf-8')) / 1024
            logger.info(f"[TOOL:FILES] Written {filepath} ({size_kb:.1f}KB)")
            
            return f"SUCCESS: File {filename} written ({size_kb:.1f}KB)"
        
        elif action == "delete":
            if not filename:
                return "ERROR: filename required for delete action"
            
            filepath = os.path.join(EXPORTS_DIR, filename)
            is_valid, error_msg = validate_path(filepath)
            if not is_valid:
                return f"ERROR: {error_msg}"
            
            if not os.path.exists(filepath):
                return f"ERROR: File {filename} does not exist"
            
            os.remove(filepath)
            logger.info(f"[TOOL:FILES] Deleted {filepath}")
            
            return f"SUCCESS: File {filename} deleted"
        
        elif action == "info":
            if not filename:
                return "ERROR: filename required for info action"
            
            filepath = os.path.join(EXPORTS_DIR, filename)
            is_valid, error_msg = validate_path(filepath)
            if not is_valid:
                return f"ERROR: {error_msg}"
            
            if not os.path.exists(filepath):
                return f"ERROR: File {filename} does not exist"
            
            stat = os.stat(filepath)
            size_kb = stat.st_size / 1024
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            created = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M")
            
            return (
                f"File Info for {filename}:\n"
                f"  Size: {size_kb:.1f}KB\n"
                f"  Created: {created}\n"
                f"  Modified: {modified}\n"
                f"  Type: {os.path.splitext(filename)[1]}"
            )
        
        else:
            return f"ERROR: Unknown action '{action}'. Valid actions: read, write, list, delete, info"
    
    except Exception as e:
        logger.error(f"[TOOL:FILES] Failed: {e}")
        return f"ERROR: File operation failed: {str(e)}"


# ============================================
# TOOL: REPORT TEMPLATER
# ============================================

@tool
def generate_report_template(
    template_type: str,
    filename: str,
    data: Optional[str] = None,
    format: str = "markdown"
) -> str:
    """
    Generate a formal audit/compliance report from a template.
    
    Args:
        template_type: One of: "audit_findings", "compliance_gap", "risk_assessment", "executive_summary"
        filename: Output filename (will be saved to /home/kuro/exports/)
        data: JSON string with report data. Required fields vary by template.
        format: Output format - "markdown" (default) or "pdf"
    
    Returns:
        Success message with file path, or error description.
    
    Example:
        generate_report_template(
            template_type="audit_findings",
            filename="iso27001_audit.md",
            data='{"title": "ISO 27001 Audit", "auditor": "Kuro", "findings": [...]}'
        )
    """
    try:
        # Validate filename
        if format == "pdf" and not filename.endswith('.pdf'):
            filename = f"{filename}.pdf"
        elif format == "markdown" and not filename.endswith('.md'):
            filename = f"{filename}.md"
        
        # Security validation
        filepath = os.path.join(EXPORTS_DIR, filename)
        is_valid, error_msg = validate_path(filepath)
        if not is_valid:
            return f"ERROR: {error_msg}"
        
        ensure_exports_dir()
        
        # Parse data
        report_data = {}
        if data:
            try:
                report_data = json.loads(data)
            except json.JSONDecodeError as e:
                return f"ERROR: Invalid JSON data: {str(e)}"
        
        # Generate report based on template type
        if template_type == "audit_findings":
            content = _generate_audit_findings_template(report_data)
        elif template_type == "compliance_gap":
            content = _generate_compliance_gap_template(report_data)
        elif template_type == "risk_assessment":
            content = _generate_risk_assessment_template(report_data)
        elif template_type == "executive_summary":
            content = _generate_executive_summary_template(report_data)
        else:
            return f"ERROR: Unknown template type '{template_type}'. Valid: audit_findings, compliance_gap, risk_assessment, executive_summary"
        
        # Write output
        if format == "markdown":
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        elif format == "pdf":
            # Try to convert markdown to PDF
            try:
                import markdown
                from weasyprint import HTML
                html = markdown.markdown(content, extensions=['tables', 'fenced_code'])
                html_full = f"""
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; }}
                        h1 {{ color: #1a1a2e; border-bottom: 2px solid #00d4ff; padding-bottom: 10px; }}
                        h2 {{ color: #16213e; }}
                        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                        th {{ background-color: #1a1a2e; color: white; }}
                        .critical {{ color: #ff6b6b; font-weight: bold; }}
                        .high {{ color: #ffa500; font-weight: bold; }}
                        .medium {{ color: #ffd700; }}
                        .low {{ color: #90ee90; }}
                    </style>
                </head>
                <body>{html}</body>
                </html>
                """
                HTML(string=html_full).write_pdf(filepath)
            except ImportError:
                # Fallback: save as markdown with .pdf extension
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(f"# PDF Generation Requires: markdown, weasyprint\n\n{content}")
                logger.warning(f"[TOOL:REPORT] PDF libraries not installed, saved as markdown")
        
        size_kb = os.path.getsize(filepath) / 1024
        logger.info(f"[TOOL:REPORT] Generated {filepath} ({size_kb:.1f}KB)")
        
        return f"SUCCESS: {template_type.replace('_', ' ').title()} report generated at {filepath} ({size_kb:.1f}KB)"
    
    except Exception as e:
        logger.error(f"[TOOL:REPORT] Failed: {e}")
        return f"ERROR: Report generation failed: {str(e)}"


# ============================================
# TEMPLATE HELPERS
# ============================================

def _generate_audit_findings_template(data: Dict) -> str:
    """Generate audit findings report template."""
    title = data.get("title", "Audit Findings Report")
    auditor = data.get("auditor", "Kuro AI")
    date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    standard = data.get("standard", "ISO 27001:2022")
    findings = data.get("findings", [])
    
    md = f"""# {title}

| Metadata | Details |
|----------|---------|
| **Standard** | {standard} |
| **Auditor** | {auditor} |
| **Date** | {date} |
| **Generated By** | Kuro AI Butler |

---

## Executive Summary

This report documents the findings of the {standard} audit conducted on {date}.

**Total Findings:** {len(findings)}

---

## Detailed Findings

"""
    
    for i, finding in enumerate(findings, 1):
        severity = finding.get("severity", "N/A").upper()
        severity_class = severity.lower() if severity.lower() in ["critical", "high", "medium", "low"] else ""
        
        md += f"""### Finding #{i}: {finding.get('title', 'Untitled')}

| Attribute | Value |
|-----------|-------|
| **Severity** | <span class="{severity_class}">{severity}</span> |
| **Clause** | {finding.get('clause', 'N/A')} |
| **Status** | {finding.get('status', 'Open')} |

**Description:**
{finding.get('description', 'No description provided.')}

**Evidence:**
{finding.get('evidence', 'No evidence documented.')}

**Recommendation:**
{finding.get('recommendation', 'No recommendation provided.')}

---

"""
    
    md += """## Sign-Off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Lead Auditor | | | |
| Auditee | | | |
| Management | | | |

---
*Report generated by Kuro AI Butler - Confidential*
"""
    
    return md


def _generate_compliance_gap_template(data: Dict) -> str:
    """Generate compliance gap analysis template."""
    title = data.get("title", "Compliance Gap Analysis")
    standard = data.get("standard", "ISO 27001:2022")
    gaps = data.get("gaps", [])
    
    md = f"""# {title}

**Standard:** {standard}
**Date:** {data.get("date", datetime.now().strftime("%Y-%m-%d"))}

---

## Gap Analysis Summary

| # | Control | Current State | Required State | Gap | Priority |
|---|---------|---------------|----------------|-----|----------|
"""
    
    for i, gap in enumerate(gaps, 1):
        md += f"| {i} | {gap.get('control', 'N/A')} | {gap.get('current', 'N/A')} | {gap.get('required', 'N/A')} | {gap.get('gap', 'N/A')} | {gap.get('priority', 'N/A')} |\n"
    
    md += """
---

## Detailed Gap Analysis

"""
    
    for i, gap in enumerate(gaps, 1):
        md += f"""### Gap #{i}: {gap.get('control', 'N/A')}

**Current State:** {gap.get('current', 'Not documented')}
**Required State:** {gap.get('required', 'Not specified')}
**Gap Description:** {gap.get('gap', 'Not described')}
**Remediation Plan:** {gap.get('remediation', 'Not provided')}

---

"""
    
    return md


def _generate_risk_assessment_template(data: Dict) -> str:
    """Generate risk assessment template."""
    title = data.get("title", "Risk Assessment Report")
    risks = data.get("risks", [])
    
    md = f"""# {title}

**Date:** {data.get("date", datetime.now().strftime("%Y-%m-%d"))}
**Assessor:** {data.get("assessor", "Kuro AI")}

---

## Risk Register

| # | Risk | Likelihood | Impact | Risk Level | Mitigation |
|---|------|------------|--------|------------|------------|
"""
    
    for i, risk in enumerate(risks, 1):
        md += f"| {i} | {risk.get('name', 'N/A')} | {risk.get('likelihood', 'N/A')} | {risk.get('impact', 'N/A')} | {risk.get('level', 'N/A')} | {risk.get('mitigation', 'N/A')} |\n"
    
    md += """
---

*Report generated by Kuro AI Butler - Confidential*
"""
    
    return md


def _generate_executive_summary_template(data: Dict) -> str:
    """Generate executive summary template."""
    title = data.get("title", "Executive Summary")
    
    md = f"""# {title}

**Date:** {data.get("date", datetime.now().strftime("%Y-%m-%d"))}
**Prepared By:** {data.get("prepared_by", "Kuro AI")}

---

## Overview

{data.get("overview", "No overview provided.")}

## Key Findings

{data.get("key_findings", "No key findings provided.")}

## Recommendations

{data.get("recommendations", "No recommendations provided.")}

## Next Steps

{data.get("next_steps", "No next steps provided.")}

---

*Report generated by Kuro AI Butler - Confidential*
"""
    
    return md


# ============================================
# TOOL REGISTRY
# ============================================

# Export all tools for LangGraph ToolNode
ALL_SYSTEM_TOOLS = [
    generate_excel_report,
    manage_files,
    generate_report_template,
]

# Tool descriptions for LLM
TOOL_DESCRIPTIONS = {
    "generate_excel_report": "Generate an Excel (.xlsx) file from JSON data. Use this when Master asks to create a spreadsheet, Excel file, or tabular report.",
    "manage_files": "Manage files in /home/kuro/exports/. Actions: list, read, write, delete, info. Use this to list files, read content, create new files, or check file info.",
    "generate_report_template": "Generate a formal audit/compliance report from templates. Types: audit_findings, compliance_gap, risk_assessment, executive_summary. Output as markdown or PDF.",
}
