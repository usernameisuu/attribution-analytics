"""Run only on the remote host: python -m app.worker."""
import logging
import threading
from datetime import timedelta
from sqlalchemy import select
from .db import SessionFactory, DatasetVersion, AnalysisSession, AuditEvent, utcnow
from .queue import claim, current, emit
from .domain.datasets import DIMENSIONS
from .domain.exploration import rule_plan, validate_scope, analyze
from . import model_gateway

log = logging.getLogger(__name__)


def heartbeat(run_id, fence, stop):
    while not stop.wait(10):
        try:
            with SessionFactory.begin() as db:
                run = current(db,run_id,fence)
                if not run: return
                run.lease_until = utcnow()+timedelta(seconds=60)
        except Exception:
            # No results can commit after expiry, even if this process survives.
            log.warning('Lease renewal failed for run %s',run_id)
            return


def process(run_id, fence):
    mode = None
    stop = threading.Event()
    pulse = threading.Thread(target=heartbeat,args=(run_id,fence,stop),daemon=True)
    pulse.start()
    try:
        with SessionFactory.begin() as db:
            run = current(db,run_id,fence)
            if not run: return
            dataset = db.get(DatasetVersion,run.dataset_id)
            question, prior, parents, mode = run.question,run.scope,run.parents,run.mode
            rows, scenario, version, digest = dataset.rows,dataset.scenario,dataset.id,dataset.digest
            source_kind=dataset.source_kind
        if mode == 'deepseek' and question.strip() != '返回上一级':
            scope = model_gateway.plan(run_id,fence,question,prior,{k:sorted({r[k] for r in rows}) for k in DIMENSIONS})
            scope = validate_scope(scope,rows)
        else:
            scope = rule_plan(question,prior,rows,parents)
        with SessionFactory.begin() as db:
            run = current(db,run_id,fence)
            if not run: return
            emit(db,run,'calculating',message='按已校验范围聚合并分解贡献',scope=scope)
        result = analyze(scenario,rows,scope,version)
        result['data_digest'] = digest
        result['data_kind'] = '合成日聚合样例（非真实业务）' if source_kind=='synthetic' else '导入的日聚合数据'
        if question.strip() == '返回上一级':
            result['scope_parents'] = parents[:-1]
        else:
            result['scope_parents'] = (parents+[prior])[-50:] if scope != prior else parents
        result['statistics'] = {'status':'unavailable','reason':'独立统计执行沙箱尚未接入；本次只完成数学分解。'}
        with SessionFactory.begin() as db:
            run = current(db,run_id,fence)
            if not run: return
            session = db.scalar(select(AnalysisSession).where(AnalysisSession.id==run.session_id).with_for_update())
            run.result, run.status, run.lease_until = result,'succeeded',None
            session.snapshot = result
            emit(db,run,'completed',message='数学分析完成，统计证据状态已明确标注')
            db.add(AuditEvent(actor_id=run.owner_id,action='run_completed',object_id=run.id,
                              details={'dataset_version':version,'digest':digest,'scope':scope,'fence':fence}))
    except ValueError as exc:
        finish_error(run_id,fence,str(exc)[:500],'needs_input' if mode=='rules' else 'failed')
    except Exception:
        log.exception('Analysis run %s failed',run_id)
        finish_error(run_id,fence,'分析执行失败，请重试；服务端日志记录了故障位置','failed')
    finally:
        stop.set()
        pulse.join(timeout=2)


def finish_error(run_id,fence,message,status):
    with SessionFactory.begin() as db:
        run = current(db,run_id,fence)
        if not run: return
        run.status,run.error,run.lease_until = status,message,None
        emit(db,run,status,message=message)


def main():
    import signal
    logging.basicConfig(level=logging.INFO)
    stopping = threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    while not stopping.is_set():
        try:
            with SessionFactory.begin() as db:
                task = claim(db)
            if task: process(*task)
            else: stopping.wait(2)
        except Exception:
            log.exception('Worker polling failed')
            stopping.wait(5)


if __name__ == '__main__':
    main()
