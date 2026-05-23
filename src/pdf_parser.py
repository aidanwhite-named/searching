import os
import tempfile
import opendataloader_pdf


class PDFParser:
    def parse(self, pdf_path: str) -> str:
        """PDF 파일을 Markdown 문자열로 변환."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 파일 없음: {pdf_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            opendataloader_pdf.convert(
                input_path=pdf_path,
                output_dir=tmpdir,
                format="markdown",
                reading_order="xycut",  # 다단 레이아웃 읽기 순서 보정
                quiet=True,
            )
            md_files = [f for f in os.listdir(tmpdir) if f.endswith(".md")]
            if not md_files:
                raise RuntimeError(f"Markdown 변환 결과 없음: {pdf_path}")
            md_path = os.path.join(tmpdir, md_files[0])
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read()
