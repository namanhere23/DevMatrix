# nexussentry/memory/episodic_memory.py
"""
Vector-based long-term memory. Stores successful task→plan pairs.
The Architect queries this before planning — it gets smarter with every run.

Uses ChromaDB for persistence and sentence-transformers for embeddings.
Gracefully degrades when dependencies are not installed.
"""
import json
import time
import hashlib
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)


class EpisodicMemory:
    def __init__(self, persist_dir: str = None):
        if persist_dir is None:
            from pathlib import Path
            persist_dir = str(Path.home() / ".nexussentry" / "memory")

        self._available = False
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer

            self.client = chromadb.PersistentClient(path=persist_dir)
            self.collection = self.client.get_or_create_collection(
                "task_episodes",
                metadata={"hnsw:space": "cosine"}
            )
            self.encoder = SentenceTransformer("all-MiniLM-L6-v2")
            self._available = True
            log.info(f"EpisodicMemory initialized. Episodes stored: {self.collection.count()}")
        except ImportError:
            log.warning("chromadb or sentence-transformers not installed. EpisodicMemory disabled.")
        except Exception as e:
            log.warning(f"EpisodicMemory init failed: {e}. Continuing without episodic memory.")

    def store_episode(self, task: str, plan: dict, result_summary: str, score: int):
        """
        Call this after every Critic approval (score >= 70).
        Only store successful patterns.
        """
        if not self._available or score < 70:
            return

        try:
            episode_id = hashlib.md5(f"{task}:{time.time()}".encode()).hexdigest()
            embedding = self.encoder.encode(task).tolist()

            self.collection.add(
                ids=[episode_id],
                embeddings=[embedding],
                documents=[task],
                metadatas=[{
                    "plan_summary": plan.get("plan_summary", "")[:500],
                    "approach": plan.get("approach", "")[:500],
                    "files_to_modify": json.dumps(plan.get("files_to_modify", [])),
                    "commands_to_run": json.dumps(plan.get("commands_to_run", [])),
                    "success_criteria": plan.get("success_criteria", "")[:300],
                    "result_summary": result_summary[:300],
                    "score": score,
                    "timestamp": time.time()
                }]
            )
            log.info(f"Episode stored (score={score}). Total episodes: {self.collection.count()}")
        except Exception as e:
            log.warning(f"Failed to store episode: {e}")

    def retrieve_similar(self, task: str, n: int = 3, min_similarity: float = 0.70) -> List[Dict]:
        """
        The Architect calls this FIRST, before generating any plan.
        Returns similar past successful approaches as few-shot examples.
        """
        if not self._available or self.collection.count() == 0:
            return []

        try:
            embedding = self.encoder.encode(task).tolist()
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=min(n, self.collection.count()),
            )

            episodes = []
            for i, doc in enumerate(results["documents"][0]):
                similarity = 1 - results["distances"][0][i]
                if similarity >= min_similarity:
                    meta = results["metadatas"][0][i]
                    episodes.append({
                        "past_task": doc,
                        "approach": meta.get("approach", ""),
                        "files_modified": json.loads(meta.get("files_to_modify", "[]")),
                        "commands": json.loads(meta.get("commands_to_run", "[]")),
                        "score": meta.get("score", 0),
                        "similarity": round(similarity, 3)
                    })

            log.info(f"Retrieved {len(episodes)} similar episodes for task (threshold={min_similarity})")
            return episodes
        except Exception as e:
            log.warning(f"Episode retrieval failed: {e}")
            return []

    def stats(self) -> dict:
        if not self._available:
            return {"available": False, "episode_count": 0}
        try:
            return {
                "available": True,
                "episode_count": self.collection.count()
            }
        except Exception:
            return {"available": False, "episode_count": 0}
