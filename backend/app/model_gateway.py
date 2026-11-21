"""One bounded JSON planning call. Unknown provider charges stay reserved."""
import json
from datetime import date
from decimal import Decimal as D, ROUND_CEILING
from urllib.request import Request, build_opener, HTTPRedirectHandler
from sqlalchemy import select
from .config import settings
from .db import SessionFactory, BudgetAccount, ModelCall
from .domain.budget import reserve_cost
from .queue import current


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def plan(run_id: str, fence: str, question: str, scope: dict, dimensions: dict) -> dict:
    cfg = settings()
    if not cfg.deepseek_key or not cfg.deepseek_key.get_secret_value():
        raise ValueError('MODEL_UNAVAILABLE：未配置 DeepSeek API Key')
    try:
        age = (date.today()-date.fromisoformat(cfg.model_price_verified_on)).days
    except ValueError as exc:
        raise ValueError('MODEL_PRICE_UNVERIFIED：未核对计费日期') from exc
    if not 0 <= age <= 7:
        raise ValueError('MODEL_PRICE_EXPIRED：请重新核对价格')
    if len(json.dumps(dimensions,ensure_ascii=False).encode())>32_000:
        raise ValueError('MODEL_DIMENSIONS_TOO_LARGE：维度字典超过当前规划输入上限，请使用规则模式')
    messages = [dict(role='system', content='你是经营分析意图解析器。只返回 JSON 对象 {"scope":...}。scope 只包含 baseline/current 两个日期对、filters 字典和 group_by。不得改变未明确要求改变的条件；filters 仅使用所提供维度值。问题不明确时返回 {"clarification":"需要澄清的问题"}。不生成 SQL、Python、数值结论或权限设置。'),
                dict(role='user',content=json.dumps(dict(question=question,scope=scope,dimensions=dimensions),ensure_ascii=False))]
    reserved = reserve_cost(messages,cfg.model_input_cny_per_million,cfg.model_output_cny_per_million)
    with SessionFactory.begin() as db:
        run = current(db,run_id,fence)
        if not run:
            raise ValueError('任务已取消或授权已撤销')
        account = db.scalar(select(BudgetAccount).where(BudgetAccount.id=='development').with_for_update())
        if not account or account.spent_cny+account.reserved_cny+reserved > min(account.limit_cny,D('25')):
            raise ValueError('MODEL_BUDGET_EXHAUSTED：需要用户批准追加预算')
        account.reserved_cny += reserved
        call = ModelCall(run_id=run_id,reserved_cny=reserved,price_version=cfg.model_price_verified_on,
                         usage={'model':cfg.deepseek_model,'input_cny_per_million':str(cfg.model_input_cny_per_million),
                                'output_cny_per_million':str(cfg.model_output_cny_per_million),'max_output_tokens':2048})
        db.add(call); db.flush(); call_id = call.id
    payload = dict(model=cfg.deepseek_model,messages=messages,max_tokens=2048,stream=False,
                   thinking={'type':'disabled'},response_format={'type':'json_object'})
    request = Request('https://api.deepseek.com/chat/completions',data=json.dumps(payload).encode(),method='POST',
                      headers={'Authorization':'Bearer '+cfg.deepseek_key.get_secret_value(),'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect()).open(request,timeout=40) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000: raise ValueError('模型响应超出大小限制')
            result = json.loads(body)
        usage = result.get('usage',{})
        tokens = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
        if any(type(n) is not int or n < 0 for n in tokens):
            raise ValueError('模型未返回可靠用量，预留费用保留待核对')
        actual = ((D(tokens[0])*cfg.model_input_cny_per_million+D(tokens[1])*cfg.model_output_cny_per_million)/D(1000000)).quantize(D('.00000001'),rounding=ROUND_CEILING)
        with SessionFactory.begin() as db:
            account = db.scalar(select(BudgetAccount).where(BudgetAccount.id=='development').with_for_update())
            call = db.get(ModelCall,call_id)
            account.reserved_cny -= call.reserved_cny
            account.spent_cny += actual
            call.actual_cny,call.usage,call.state = actual,{**call.usage,'provider_usage':usage},'settled'
        if actual > reserved:
            raise ValueError('MODEL_PRICE_MISMATCH：实际计费超过预留，需人工核对')
        answer = json.loads(result['choices'][0]['message']['content'])
        if not isinstance(answer,dict) or set(answer) not in ({'scope'}, {'clarification'}):
            raise ValueError('模型输出不符合计划合同')
        if 'clarification' in answer:
            raise ValueError(str(answer['clarification'])[:400])
        return answer['scope']
    except Exception:
        with SessionFactory.begin() as db:
            call = db.get(ModelCall,call_id)
            if call.state == 'reserved': call.state = 'usage_unknown'
        raise ValueError('MODEL_CALL_FAILED：调用失败或输出无效；已知用量已结算，未知用量保留预留额度') from None
