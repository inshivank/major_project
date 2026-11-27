"""Temporary synthetic-only trace; never prints credentials or vendor bodies."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.agents.report_agent import ReportAgent
from backend.reports.extraction import DocumentExtractor
from backend.rag.retriever import Retriever
from backend.llm.llm_service import LLMService

class TraceLLM(LLMService):
    @property
    def client(self):
        client = super().client
        if not getattr(self, '_traced', False):
            original = client.chat.completions.create
            def traced(**kwargs):
                try:
                    response = original(**kwargs)
                    print(json.dumps({'finish_reason':response.choices[0].finish_reason,'content_chars':len(response.choices[0].message.content or ''),'completion_tokens':getattr(response.usage,'completion_tokens',None)}),flush=True)
                    return response
                except Exception as exc:
                    body = getattr(exc, 'body', {}) or {}
                    error = body.get('error',body) if isinstance(body,dict) else {}
                    cause = exc.__cause__
                    print(json.dumps({'sdk_error': type(exc).__name__, 'status': getattr(exc,'status_code',None), 'provider_code': error.get('code') if isinstance(error,dict) else None, 'cause': type(cause).__name__ if cause else None, 'retry_after': getattr(exc,'response',None).headers.get('retry-after') if getattr(exc,'response',None) is not None else None}), flush=True)
                    raise
            client.chat.completions.create = traced
            self._traced = True
        return client
    def complete_json(self,messages,**kwargs):
        data=json.loads(messages[-1]['content'])
        print(json.dumps({'evidence_ids':[x['source'] for x in data['evidence']], 'evidence_count':len(data['evidence'])}),flush=True)
        Path('reports/runtime/groq_synthetic_prompt.json').write_text(json.dumps(messages,indent=2),encoding='utf-8')
        try:
            result=super().complete_json(messages,**kwargs)
        except Exception as exc:
            print(json.dumps({'error_class':type(exc).__name__,'safe_message':str(exc) if type(exc).__name__ == 'LLMError' else None,'status_code':getattr(exc,'status_code',None),'cause_class':type(exc.__cause__).__name__ if exc.__cause__ else None}),flush=True)
            raise
        Path('reports/runtime/groq_synthetic_output.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'generated_payload':result}),flush=True)
        return result

if __name__=='__main__':
    r=Retriever()
    chunks=r.retrieve('Hemoglobin laboratory test patient education',k=2)
    print(json.dumps({'retrieval_count':len(chunks),'sources':[{'title':c.title,'url':c.url,'score':c.score} for c in chunks]}),flush=True)
    agent=ReportAgent(extractor=DocumentExtractor(),retriever=r,llm=TraceLLM(max_retries=1))
    response=agent.analyze(Path('reports/runtime/synthetic_cbc_text.pdf').read_bytes(),consent=True)
    print(json.dumps({'external_llm_used':response.external_llm_used,'warnings':response.warnings,'source_types':[s.type.value for s in response.sources]}),flush=True)
