"""多格式文档解析器，支持 MD/TXT/PDF/网页"""
from src.knowledge.parsers.pdf_parser import parse_pdf
from src.knowledge.parsers.web_parser import parse_web

__all__ = ["parse_pdf", "parse_web"]
