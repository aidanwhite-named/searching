import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[reranker] Loading reranker model '{model_name}' on device '{self.device}'")
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
        self.model.eval()
        print("[reranker] Reranker model loaded successfully.")

    def rerank(self, query: str, candidates: list, top_k: int = 10) -> list:
        """
        Rerank candidate chunks based on similarity to query text.
        candidates: list of tuple(Chunk, float) or list of Chunk.
        Returns: list of tuple(Chunk, float) sorted by reranker score descending, limited to top_k.
        """
        if not candidates:
            return []
            
        # Standardize candidates to list of Chunk
        chunks = []
        for c in candidates:
            if isinstance(c, tuple):
                chunks.append(c[0])
            else:
                chunks.append(c)
                
        # Build query-passage pairs
        pairs = [[query, chunk.text] for chunk in chunks]
        
        try:
            with torch.no_grad():
                inputs = self.tokenizer(
                    pairs, 
                    padding=True, 
                    truncation=True, 
                    return_tensors='pt', 
                    max_length=512
                ).to(self.device)
                
                # Predict scores
                logits = self.model(**inputs).logits.view(-1,)
                # Convert logits to probability range 0-1 using sigmoid
                scores = torch.sigmoid(logits).cpu().numpy().tolist()
                
            # Zip chunks with scores and sort descending
            scored = [(chunks[idx], float(scores[idx])) for idx in range(len(chunks))]
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
            
        except Exception as e:
            print(f"[reranker] Semantic reranking failed: {e}")
            # Return original candidates order with dummy scores as fallback
            return [(chunks[idx], 1.0 / (idx + 1)) for idx in range(len(chunks))][:top_k]
