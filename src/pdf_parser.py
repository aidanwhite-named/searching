import logging
import os
import tempfile
import pypdfium2 as pdfium

logger = logging.getLogger(__name__)


class PDFParser:
    def parse(self, pdf_path: str) -> str:
        """PDF → 텍스트 변환. pypdfium2(Chrome 엔진) 우선, 실패 시 opendataloader 폴백."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 파일 없음: {pdf_path}")

        # 1차: pypdfium2 (한국어 포함 모든 PDF에 강건)
        try:
            text = self._parse_with_pdfium(pdf_path)
            if text.strip():
                return text
        except Exception as e:
            logger.warning("pypdfium2 실패: %s → opendataloader 폴백", e)

        # 2차: opendataloader-pdf (레이아웃 인식 마크다운)
        try:
            return self._parse_with_opendataloader(pdf_path)
        except Exception as e:
            raise RuntimeError(f"PDF 텍스트 추출 실패: {pdf_path}") from e

    def _parse_with_pdfium(self, pdf_path: str) -> str:
        pdf = pdfium.PdfDocument(pdf_path)
        pages = []
        for page in pdf:
            textpage = page.get_textpage()
            pages.append(textpage.get_text_range())
        return "\n\n".join(pages)

    def _parse_with_opendataloader(self, pdf_path: str) -> str:
        import opendataloader_pdf
        with tempfile.TemporaryDirectory() as tmpdir:
            opendataloader_pdf.convert(
                input_path=pdf_path,
                output_dir=tmpdir,
                format="markdown",
                reading_order="xycut",
                quiet=True,
            )
            md_files = [f for f in os.listdir(tmpdir) if f.endswith(".md")]
            if not md_files:
                raise RuntimeError("Markdown 변환 결과 없음")
            md_path = os.path.join(tmpdir, md_files[0])
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    with open(md_path, "r", encoding=enc) as f:
                        return f.read()
                except UnicodeDecodeError:
                    continue
            with open(md_path, "rb") as f:
                return f.read().decode("utf-8", errors="replace")
