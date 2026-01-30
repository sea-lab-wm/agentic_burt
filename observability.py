from langchain_core.callbacks import BaseCallbackHandler
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import json
from pathlib import Path


#Format of AIMessage that our call back handler should recieve: AIMessage(
# content="J'adore la programmation.", 
# additional_kwargs={'refusal': None}, 
# response_metadata=
    # {
        # 'token_usage': # {'completion_tokens': 5, 'prompt_tokens': 31, 'total_tokens': 36}, 
        # 'model_name': 'gpt-4o-2024-05-13', 
        # 'system_fingerprint': 'fp_3aa7262c27', 
        # 'finish_reason': 'stop', 
        # 'logprobs': None}
# id='run-63219b22-03e3-4561-8cc4-78b7c7c3a3ca-0', 
# usage_metadata={'input_tokens': 31, 'output_tokens': 5, 'total_tokens': 36})
def _extract_usage(response: Any) -> Optional[Dict[str, int]]:
    """
    Extracts token usage from LLM call
    """
    usage = response.get("usage_metadata")

    #NOTE:-1 indicates that we could not extract token value
    if isinstance(usage, dict):
        p = int(usage.get("input_tokens", 0) or -1)
        c = int(usage.get("output_tokens", 0) or -1)
        t = int(usage.get("total_tokens", 0) or -1)
        return {"input_tokens": p, "output_tokens": c, "total_tokens": t}
        
    return None

@dataclass
class LLMEvent:
    input_tokens: int
    output_tokens: int
    total_tokens: int


class TokenEventCollector(BaseCallbackHandler):
    """
    Collects a list of token-usage events for every LLM call.
    """
    def __init__(self):
        self.events: List[LLMEvent] = []

    def on_llm_end(self, response, *, run_id, parent_run_id = None, **kwargs):
        usage = _extract_usage(response)
        if not usage:
            print(f"Failed to Extract Usage")
            return
        
        self.events.append(LLMEvent(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"], 
            total_tokens=usage["total_tokens"]
        ))

class JSONLNodeLogger:
    """
    Writes one JSON line per node activation.
    """

    def __init__(self, filepath: str, conversation_id: str):
        self.path = Path(filepath)
        self.conversation_id = conversation_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
    
    