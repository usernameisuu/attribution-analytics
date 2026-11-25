"""Cross-module synthetic workflows in temporary SQLite; HTTP and PostgreSQL are not exercised."""
import os
from io import BytesIO
from unittest.mock import patch

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

with patch.dict(os.environ, {'ATTRIBUTION_DATABASE_URL':'postgresql+psycopg://unused@127.0.0.1/unused'}):
    from app.db import AnalysisRun, Base, User
    from app.event_api import EventInput, create_business_event, session_business_events
    from app.modules.analysis.api import Comparison, ReportNote, SimulationScenario, compare_dataset, get_baseline_variability, report_preview, save_report_note
    from app.modules.analysis.archive_api import ArchiveInput, create_archive, export_archive
    from app.modules.analysis.service import compare_simulations, create, preview_simulations, run_daily_check
    from app.pipeline_api import DemoInput, RunInput, create_run, demo_dataset, restore_previous_draft
    from app.worker import process


@pytest.mark.parametrize('scenario', ['ecommerce', 'consumer'])
def test_synthetic_workflow_across_modules(tmp_path, scenario):
    engine = create_engine(f"sqlite:///{tmp_path / 'workflow.sqlite'}", connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(User(id='owner', username='owner', password_hash='unused', role='analyst',
                    domains=['ecommerce','consumer'], active=True))
    with factory() as db:
        user = db.get(User, 'owner')
        dataset = demo_dataset(DemoInput(scenario=scenario), db, user)
        session = create(db, user, scenario, dataset['id'], None)
        sid = session['id']
        comparison = compare_dataset(dataset['id'], Comparison(scope=session['scope'], threshold='1'), db, user)
        assert comparison['status'] == 'anomaly'
        variability = get_baseline_variability(sid, db, user)
        assert variability['days'] == 30 and variability['data_digest'] == dataset['digest']
        factor = 'conversion' if scenario == 'ecommerce' else 'material'
        value = '0.04' if scenario == 'ecommerce' else session['parameters']['material']
        scenarios = [SimulationScenario(name='隔离情景', changes={factor:value})]
        preview = preview_simulations(db, user, sid, session['analysis_revision'], scenarios)
        session = compare_simulations(db, user, sid, session['analysis_revision'], session['simulation_revision'], scenarios)
        assert session['simulation_scenarios'][0]['prediction'] == preview[0]['prediction']
        create_business_event(EventInput(scenario=scenario, title='测试活动', start='2026-10-01', end='2026-10-02',
                                        source='模拟记录', scope={'region':['华东']}), db, user)
        events = session_business_events(sid, db, user)
        assert len(events['events']) == 1 and '不证明因果' in events['notice']
        session = run_daily_check(db, user, sid, session['analysis_revision'], session['statistics_revision'], 0.95, factor)
        check = session['statistical_checks'][0]
        assert check['factor_key'] == factor
        assert check['status'] == ('computed' if scenario == 'ecommerce' else 'not_applicable')
        if scenario == 'consumer':
            assert '均无波动' in check['reason']
        assert any('不能确认或排除' in limit for limit in check['limitations'])
        group = '付费投放' if scenario == 'ecommerce' else '服饰'
        session = run_daily_check(db, user, sid, session['analysis_revision'], session['statistics_revision'], 0.95, factor, group)
        group_check = session['statistical_checks'][-1]
        assert group_check['group_value'] == group
        assert group_check['status'] == ('computed' if scenario == 'ecommerce' else 'not_applicable')
        assert any('未控制混杂' in limit for limit in group_check['limitations'])
        session = run_daily_check(db, user, sid, session['analysis_revision'], session['statistics_revision'], 0.95)
        assert [(item['factor_key'],item['group_value']) for item in session['statistical_checks']] == [(factor,None),(factor,group),(None,None)]
        session = save_report_note(sid, ReportNote(revision=session['report_revision'], text='待核对活动数据'), db, user)
        preview = report_preview(sid, db, user, revision=session['report_revision'])
        assert '待核对活动数据' in preview['markdown'] and '测试活动' in preview['markdown'] and check['metric'] in preview['markdown']
        assert '分组对比' in preview['markdown'] and group in preview['markdown']
        assert '相关逐日检验（按因子关联' in preview['markdown'] and group_check['metric'] in preview['markdown']
        archive = create_archive(sid, ArchiveInput(revision=session['report_revision']), db, user)
        report = export_archive(archive['id'], 'md', db, user).body.decode('utf-8')
        assert '隔离情景' in report and '测试活动' in report and '基期每日波动参考' in report and '待核对活动数据' in report
        assert 'daily-welch-v5' in report and dataset['digest'] in report and session['scope']['baseline'][0] in report
        excel = export_archive(archive['id'], 'xlsx', db, user)
        workbook = load_workbook(BytesIO(excel.body), data_only=False)
        stats = workbook['每日均值检验']
        cells = {cell.value: stats.cell(2, cell.column).value for cell in stats[1]}
        assert cells['方法版本'] == 'daily-welch-v5' and cells['摘要'] == dataset['digest']
        assert session['scope']['baseline'][0] in cells['检验范围'] and cells['候选因子'] == factor
        second = {cell.value: stats.cell(3, cell.column).value for cell in stats[1]}
        third = {cell.value: stats.cell(4, cell.column).value for cell in stats[1]}
        assert second['分组值'] == group and third['候选因子'] == '整体指标'
        candidates = workbook['候选问题与观察']
        header = {cell.value: cell.column for cell in candidates[1]}
        assert factor in {candidates.cell(index,header['关联因子键']).value for index in range(2,candidates.max_row+1)}
        run = create_run(sid, RunInput(question='只看华东', mode='rules', request_key='workflow-key'), db, user)
    with factory.begin() as db:
        task = db.get(AnalysisRun, run['id'])
        task.status, task.fence = 'running', 'fixture-fence'

    def current_without_lease(db, run_id, fence):
        task = db.get(AnalysisRun, run_id)
        return task if task and task.status == 'running' and task.fence == fence else None

    with patch('app.worker.SessionFactory', factory), patch('app.worker.current', current_without_lease):
        process(run['id'], 'fixture-fence')
    with factory() as db:
        task = db.get(AnalysisRun, run['id'])
        assert task.status == 'succeeded' and task.result['scope']['filters'] == {'region':'华东'}
        restored = restore_previous_draft(run['id'], db, db.get(User, 'owner'))
        assert restored['simulation_scenarios'][0]['name'] == '隔离情景'
        assert restored['report_note']['text'] == '待核对活动数据'
        assert restored['statistical_checks'][0]['factor_key'] == factor
        assert restored['statistical_checks'][1]['group_value'] == group
        assert restored['statistical_checks'][2]['factor_key'] is None
        assert restored['scope']['filters'] == {}
    engine.dispose()
