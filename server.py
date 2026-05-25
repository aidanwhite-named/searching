import os
import json
import uuid
import traceback
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.config_manager import ConfigManager
from src.llm_router import LLMRouter
from src.patent_preprocessor import PatentPreprocessor
from src.claims_parser import ClaimsParser
from src.search_pipeline import SearchPipeline
from src.rag_pipeline import RAGPipeline
from src.document_cache import DocumentCache
from src.matcher import Matcher
from src.hallucination_checker import HallucinationChecker
from src.output_formatter import OutputFormatter

# ── 전역 싱글톤: 서버 시작 시 한 번만 초기화 ────────────────────────────────
_cfg: ConfigManager = None
_router: LLMRouter = None
_preprocessor: PatentPreprocessor = None
_claims_parser: ClaimsParser = None
_cache: DocumentCache = None
_rag: RAGPipeline = None
_matcher: Matcher = None
_checker: HallucinationChecker = None
_formatter: OutputFormatter = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작 시 무거운 모델을 한 번만 로드한다."""
    global _cfg, _router, _preprocessor, _claims_parser
    global _cache, _rag, _matcher, _checker, _formatter

    print("[startup] 설정 및 경량 컴포넌트 초기화...")
    _cfg          = ConfigManager()
    _router       = LLMRouter(_cfg)
    _preprocessor = PatentPreprocessor(router=_router)
    _claims_parser = ClaimsParser()
    _cache        = DocumentCache()
    _matcher      = Matcher(
        tolerance_band=0.05,
        max_refs=_cfg.get("search", "max_results", default=2),
    )
    _checker   = HallucinationChecker()
    _formatter = OutputFormatter()

    print("[startup] 임베딩/리랭커 모델 로드 중 (최초 실행 시 다운로드 포함)...")
    _rag = RAGPipeline(_cfg)   # Embedder + Reranker 여기서 딱 한 번만 로드
    print("[startup] 모든 컴포넌트 준비 완료. 서버 요청 수신 시작.")

    yield  # 서버 실행 구간

    print("[shutdown] 서버 종료.")


app = FastAPI(title="특허 선행기술조사 시스템 웹 대시보드", lifespan=lifespan)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("output", exist_ok=True)

# In-memory tasks store
tasks = {}
history_lock = threading.Lock()
HISTORY_FILE = "output/history.json"

def get_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def update_history(task_id, pdf_filename, patent_title, timestamp, status, error_msg=None):
    with history_lock:
        history = get_history()
        found = False
        for item in history:
            if item["task_id"] == task_id:
                item["status"] = status
                if patent_title != "Unknown Patent" or item["patent_title"] == "분석 중...":
                    item["patent_title"] = patent_title
                item["error_msg"] = error_msg
                found = True
                break
        if not found:
            history.append({
                "task_id": task_id,
                "pdf_filename": pdf_filename,
                "patent_title": patent_title,
                "timestamp": timestamp,
                "status": status,
                "error_msg": error_msg
            })
        # Sort history by timestamp descending
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

def run_patent_analysis(task_id, pdf_path, tolerance, max_refs, no_llm, target_claims_str):
    try:
        tasks[task_id]["status"] = "running"
        tasks[task_id]["progress"] = 10
        tasks[task_id]["message"] = "PDF 변환 및 특허 문서 전처리 중..."

        # 전역 싱글톤 재사용 (모델 재로드 없음)
        matcher = Matcher(tolerance_band=tolerance, max_refs=max_refs)

        # 1. Process PDF
        data = _preprocessor.process(pdf_path)
        nodes = _claims_parser.parse(data.claims_markdown)
        
        tasks[task_id]["progress"] = 30
        tasks[task_id]["message"] = f"특허 파싱 완료 (독립항 및 청구항 의존성 분석). 외부 DB 검색 중..."
        
        # Determine target claims
        target = None
        if target_claims_str:
            target = [int(c.strip()) for c in target_claims_str.split(",") if c.strip().isdigit()]
            
        # 2. External DB Search
        pipeline = SearchPipeline(_router, _cfg)
        search_results = pipeline.run(
            patent_data=data,
            claim_nodes=nodes,
            target_claims=target,
            max_per_db=_cfg.get("search", "max_results", default=10)
        )

        tasks[task_id]["progress"] = 55
        tasks[task_id]["message"] = "외부 DB 검색 완료. RAG 인덱스 구축 및 유사 청크 벡터 검색 중..."

        # 3. Build RAG Index (force_rebuild=True: 요청마다 새 문서로 인덱스 재구성)
        n_chunks = _rag.build_index(search_results, _cache, force_rebuild=True)
        if n_chunks == 0:
            raise Exception("인덱싱할 문서를 찾지 못했거나 외부 검색 결과가 비어 있습니다.")

        tasks[task_id]["progress"] = 70
        tasks[task_id]["message"] = "로컬 RAG 문서 데이터 베이스 구축 완료. 특허 청구항 거절논리 매칭 중..."

        all_claim_nums = sorted(nodes.keys())
        rag_results = _rag.search(nodes, all_claim_nums, top_k=10)
        
        # 4. Patent claim matching
        claim_matches = matcher.match(nodes, rag_results)
        
        tasks[task_id]["progress"] = 80
        # 5. Hallucination checks / Verification using LLM
        if not no_llm:
            tasks[task_id]["message"] = "매칭 완료. LLM 기반 선행기술 문서 단락 검증 및 분석 진행 중..."
            for idx, cm in enumerate(claim_matches):
                tasks[task_id]["message"] = f"LLM 단락 검증 중: 청구항 {cm.claim_number} ({idx+1}/{len(claim_matches)})..."
                refs_to_check = ([cm.primary_ref] if cm.primary_ref else []) + cm.secondary_refs
                for dm in refs_to_check:
                    if not dm.matched_paragraph:
                        claim_node = nodes.get(cm.claim_number)
                        if claim_node:
                            para, verified = _checker.find_and_verify(
                                cm.claim_number, claim_node.text, dm, _router, _cache
                            )
                            dm.matched_paragraph = para
                            dm.paragraph_verified = verified
                
                # Slowly bump up progress
                tasks[task_id]["progress"] = 80 + int(15 * (idx + 1) / len(claim_matches))
        else:
            tasks[task_id]["message"] = "매칭 완료 (LLM 단락 검증 생략됨)."
            tasks[task_id]["progress"] = 95
            
        # 6. Generate reports
        result_json_str = _formatter.to_json(data, claim_matches, nodes)
        result_dict = json.loads(result_json_str)

        # Inject claim texts, parents, and children for the Web UI
        for match_item in result_dict.get("claim_matches", []):
            num = match_item["claim_number"]
            node = nodes.get(num)
            if node:
                match_item["claim_text"] = node.text
                match_item["parents"] = node.parents
                match_item["children"] = node.children

        # Inject dependency tree string into metadata
        result_dict["metadata"]["dependency_tree"] = _claims_parser.render_tree(nodes)
        
        tasks[task_id]["progress"] = 100
        tasks[task_id]["message"] = "특허 선행기술조사 분석 완료!"
        tasks[task_id]["status"] = "success"
        tasks[task_id]["result"] = result_dict
        
        # Save JSON output
        out_filename = f"report_{task_id}.json"
        out_path = os.path.join("output", out_filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
            
        # Save CSV output
        csv_content = formatter.to_csv(claim_matches)
        csv_filename = f"report_{task_id}.csv"
        csv_path = os.path.join("output", csv_filename)
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)
            
        update_history(task_id, tasks[task_id]["pdf_filename"], data.title or "Unknown Patent", tasks[task_id]["timestamp"], "success")
        
    except Exception as e:
        error_msg = str(e)
        print(f"Error in analysis task {task_id}: {error_msg}")
        traceback.print_exc()
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = error_msg
        tasks[task_id]["message"] = f"오류 발생: {error_msg}"
        update_history(task_id, tasks[task_id]["pdf_filename"], "Unknown Patent", tasks[task_id]["timestamp"], "failed", error_msg=error_msg)

@app.get("/api/config")
def get_config():
    return _cfg.config

@app.post("/api/config")
def update_config(new_config: dict):
    for section, keys in new_config.items():
        if isinstance(keys, dict):
            for key, val in keys.items():
                _cfg.set(section, key, value=val)
    _cfg.save()
    return {"status": "success", "config": _cfg.config}

@app.post("/api/analyze")
def analyze(
    file: UploadFile = File(...),
    tolerance: float = Form(0.05),
    max_refs: int = Form(2),
    no_llm: bool = Form(False),
    claims: str = Form(None)
):
    task_id = str(uuid.uuid4())
    pdf_filename = file.filename
    pdf_path = os.path.join(UPLOAD_DIR, f"{task_id}_{pdf_filename}")
    
    with open(pdf_path, "wb") as f:
        f.write(file.file.read())
        
    tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "progress": 0,
        "message": "분석 작업 대기 중...",
        "error": None,
        "result": None,
        "pdf_filename": pdf_filename,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    update_history(task_id, pdf_filename, "분석 중...", tasks[task_id]["timestamp"], "running")
    
    thread = threading.Thread(
        target=run_patent_analysis,
        args=(task_id, pdf_path, tolerance, max_refs, no_llm, claims)
    )
    thread.daemon = True
    thread.start()
    
    return {"task_id": task_id}

@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    if task_id in tasks:
        return tasks[task_id]
    
    # Check history registry
    history = get_history()
    for item in history:
        if item["task_id"] == task_id:
            result = None
            if item["status"] == "success":
                filepath = os.path.join("output", f"report_{task_id}.json")
                if os.path.exists(filepath):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            result = json.load(f)
                    except:
                        pass
            return {
                "task_id": task_id,
                "status": item["status"],
                "progress": 100 if item["status"] == "success" else 0,
                "message": "분석 완료" if item["status"] == "success" else f"실패: {item.get('error_msg')}",
                "error": item.get("error_msg"),
                "result": result,
                "pdf_filename": item["pdf_filename"],
                "timestamp": item["timestamp"]
            }
            
    raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

@app.get("/api/history")
def get_history_api():
    return get_history()

@app.get("/api/reports/{task_id}")
def get_report(task_id: str):
    filepath = os.path.join("output", f"report_{task_id}.json")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="분석 레포트를 찾을 수 없습니다.")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"레포트 파일을 읽는 데 실패했습니다: {str(e)}")

@app.get("/api/reports/{task_id}/download")
def download_report(task_id: str, format: str = "json"):
    filename = f"report_{task_id}.{format}"
    filepath = os.path.join("output", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="다운로드할 레포트 파일이 없습니다.")
    media_types = {
        "json": "application/json",
        "csv": "text/csv"
    }
    return FileResponse(
        filepath, 
        media_type=media_types.get(format, "application/octet-stream"), 
        filename=filename
    )

# Mount frontend web interface
app.mount("/static", StaticFiles(directory="web"), name="static")

@app.get("/")
def read_root():
    return FileResponse("web/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8001, reload=True)
