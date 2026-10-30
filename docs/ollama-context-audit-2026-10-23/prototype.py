"""Opt-in audit prototype. Never changes a live provider or persistent settings."""
from copy import deepcopy
import json


def compact_generation(payload):
    result=deepcopy(payload)
    catalog={json.dumps(e,sort_keys=True,ensure_ascii=False) for e in payload['source_catalog']}
    grouped={}
    for key,value in payload['candidate_facts'].items():
        if isinstance(value,list) and all(isinstance(e,dict) and 'source_id'in e for e in value):
            remaining=[e for e in value if json.dumps(e,sort_keys=True,ensure_ascii=False) not in catalog]
            if remaining:grouped[key]=remaining
        else:
            grouped[key]=value
    result['candidate_facts']=grouped
    result.pop('retrieval',None)
    # Eligibility and evidence are still verified by the server-side skills bank.
    # Preserve every candidate choice, its exact ID, wording and documented level.
    result['eligible_skills']=[{k:v for k,v in s.items() if k!='evidence'} for s in payload['eligible_skills']]
    summary=result['analysis_summary']
    if summary.get('key_requirements')==[r['name'] for r in summary.get('requirements_with_evidence',[])]:
        summary.pop('key_requirements',None)
    if result.get('layout_constraints')==result.get('layout_guide'):
        result.pop('layout_constraints',None)
    if not result.get('reference_cvs_style_only'):result.pop('reference_cvs_style_only',None)
    assert result['source_catalog']==payload['source_catalog']
    assert result['analysis_summary'].get('requirements_with_evidence')==payload['analysis_summary'].get('requirements_with_evidence')
    assert result['analysis_summary'].get('role_competencies')==payload['analysis_summary'].get('role_competencies')
    assert [(s['id'],s.get('wording'),s.get('level')) for s in result['eligible_skills']]==[(s['id'],s.get('wording'),s.get('level')) for s in payload['eligible_skills']]
    return result


ANALYSIS_LEGEND='\nIn this wire format, evidence_owners rows use evidence_owner_fields; evidence strength codes resolve through evidence_strengths. These are exact aliases, never competence upgrades.'


def compact_analysis(payload):
    result=deepcopy(payload)
    codes={value:chr(65+i) for i,value in enumerate(dict.fromkeys(v[-1] for v in payload['evidence'].values()))}
    result['evidence_strengths']={code:value for value,code in codes.items()}
    result['evidence']={fid:row[:-1]+[codes[row[-1]]] for fid,row in payload['evidence'].items()}
    result['evidence_owner_fields']=['name','employment_index']
    result['evidence_owners']={oid:[value['name'],value['employment_index']] for oid,value in payload['evidence_owners'].items()}
    # This is a server-side assessment guard, not job text or candidate evidence.
    # Keep the explicit requires_assessment flag and all actual section hints.
    result['passages']=[{k:v for k,v in p.items() if k!='context_only'} for p in payload['passages']]
    assert {fid:row[:-1]+[result['evidence_strengths'][row[-1]]] for fid,row in result['evidence'].items()}==payload['evidence']
    assert {oid:dict(zip(result['evidence_owner_fields'],row)) for oid,row in result['evidence_owners'].items()}==payload['evidence_owners']
    assert result['employment_dates']==payload['employment_dates']
    assert result['passages']==[{k:v for k,v in p.items() if k!='context_only'} for p in payload['passages']]
    return result


def install_test_prototype(provider_module, tokenizer, result):
    original_chat=provider_module.OllamaProvider._chat
    original_planner=provider_module.plan_batches
    result['optimization_variant']='v2_lossless_tables_analysis6144_generation4096'

    def tokens(value):
        text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'))
        return len(tokenizer.encode(text,add_special_tokens=False).ids)

    def exact_planner(inventory, output_limit, context_limit):
        output_limit=6144
        batches,current,cost=[],[],0
        # Includes both chat role delimiters and the non-thinking assistant prefix.
        system=provider_module.TRUTH_RULES+'\n\n'+provider_module.COMPACT_PROMPT+ANALYSIS_LEGEND
        reserve=tokens(system)+17+512
        for pid,passage in inventory.passages.items():
            qualification=any(h in {'mandatory','preferred','nice_to_have','competency'} for h in passage['hints'])
            row_cost=160+min(1200,len(passage['text'])//6) if qualification else 100 if not passage['hints'] else 40
            proposed=current+[pid]
            def fits(ids):return tokens(compact_analysis(inventory.payload(ids)))+reserve+output_limit<=context_limit
            if current and (cost+row_cost>int(output_limit*0.75) or not fits(proposed)):
                batches.append(current);current=[];cost=0;proposed=[pid]
            if not fits(proposed):
                raise RuntimeError('Full candidate evidence exceeds the measured context budget; facts cannot be dropped')
            current=proposed;cost+=row_cost
        if current:batches.append(current)
        assert [pid for batch in batches for pid in batch]==list(inventory.passages)
        result['exact_planner']={'batches':[len(b) for b in batches],'facts':len(inventory.evidence),
            'tokens':[tokens(compact_analysis(inventory.payload(b)))+reserve for b in batches],
            'response_reserve':output_limit,'safety_margin':512,'schema_is_output_grammar':True}
        return batches

    async def compact_chat(self,response_model,system_prompt,payload,**kwargs):
        original=payload
        if payload.get('stage')=='tailor_resume':payload=compact_generation(payload)
        elif payload.get('stage')=='analyze_job':
            payload=compact_analysis(payload)
            system_prompt+=ANALYSIS_LEGEND
            kwargs['_completion_budget']=6144
        result.setdefault('payload_optimization',[]).append({'stage':payload.get('stage'),
            'before_tokens':tokens(original),'after_tokens':tokens(payload),
            'analysis_evidence_unchanged':payload.get('evidence')==original.get('evidence'),
            'analysis_evidence_losslessly_reencoded':payload.get('stage')=='analyze_job'})
        prompt=tokens(provider_module.TRUTH_RULES+'\n\n'+system_prompt)+tokens(payload)+(128 if kwargs.get('_think') else 17)
        output=kwargs.get('_completion_budget') or self.num_predict
        result.setdefault('request_token_budgets',[]).append({'stage':payload.get('stage'),
            'prompt_tokens_bound':prompt,'output_budget':output,'safety_margin':512,'num_ctx':self.num_ctx})
        if prompt+output+512>self.num_ctx:
            raise RuntimeError('Exact preflight refuses an oversized request; canonical facts are preserved')
        # The complete schema stays intact. The model output and independent
        # Truth Lock use the original canonical source IDs and profile.
        return await original_chat(self,response_model,system_prompt,payload,**kwargs)

    provider_module.plan_batches=exact_planner
    provider_module.OllamaProvider._chat=compact_chat
    return original_chat,original_planner
