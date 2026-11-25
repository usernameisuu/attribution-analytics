"""Analysis application boundaries, without connecting to PostgreSQL."""
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

with patch.dict(os.environ, {"ATTRIBUTION_DATABASE_URL": "postgresql+psycopg://unused:unused@127.0.0.1/unused"}):
    from app.db import AnalysisSession, AuditEvent
    from app.modules.analysis import service
    from app.modules.analysis.api import ActionItem, Comparison, DrilldownExport, NewAnalysis, SimulationScenario, audit_drilldown_export, compare_dataset, markdown_report, metric_catalog, pdf_report, spreadsheet_report, router
    from app.modules.analysis.snapshot import analysis_revision, draft_revision, drilldown_revision, serialize_session
    from app.modules.datasets.access import dataset_owned


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    def flush(self):
        for item in self.added:
            if isinstance(item, AnalysisSession):
                item.id = "session-1"

    def commit(self):
        self.commits += 1


def user(role="analyst"):
    return SimpleNamespace(id="user-1", active=True, role=role, domains=["ecommerce"])


def test_duplicate_json_field_is_rejected_without_writing():
    from app.pipeline_api import DatasetInput, import_dataset
    db = FakeDB()
    payload = DatasetInput(scenario='ecommerce', name='test', format='json',
                           content='[{"revenue": "100", "revenue": "1"}]')
    with pytest.raises(HTTPException) as error:
        import_dataset(payload, db, user())
    assert error.value.status_code == 422 and '重复字段' in error.value.detail
    assert not db.added and db.commits == 0


def test_fixed_fixture_creates_audited_snapshot_and_simulates():
    db = FakeDB()
    snapshot = service.create(db, user(), "ecommerce", None, None)
    assert snapshot["id"] == "session-1"
    assert snapshot["breakdown"]["delta"] == "-352000.00"
    audit = next(item for item in db.added if isinstance(item, AuditEvent))
    assert audit.action == "analysis_created"
    assert audit.details["dataset_version"] == snapshot["dataset_version"]
    record = next(item for item in db.added if isinstance(item, AnalysisSession))
    with patch("app.modules.analysis.service.owned", return_value=record):
        result = service.simulate(db, user(), "session-1", {"conversion": "0.035"})
        assert float(result["improvement"]) == 108000
        with pytest.raises(HTTPException) as failure:
            service.simulate(db, user("manager"), "session-1", {"conversion": "0.035"})
        assert failure.value.status_code == 403
    assert db.commits == 2


def test_rejects_unauthorized_mismatched_and_empty_scope():
    db = FakeDB()
    with pytest.raises(HTTPException) as failure:
        service.create(db, user("manager"), "ecommerce", None, None)
    assert failure.value.status_code == 403
    dataset = SimpleNamespace(id="data-1", scenario="consumer", rows=[], digest="digest", source_kind="synthetic")
    with patch("app.modules.analysis.service.dataset_owned", return_value=dataset):
        with pytest.raises(HTTPException) as failure:
            service.create(db, user(), "ecommerce", dataset.id, None)
        assert failure.value.status_code == 422
        dataset.scenario = "ecommerce"
        with pytest.raises(HTTPException) as failure:
            service.create(db, user(), "ecommerce", dataset.id, {})
        assert failure.value.status_code == 422
    assert db.commits == 0
    assert not db.added


def test_analysis_routes_remain_registered():
    from app.main import app
    paths = app.openapi()["paths"]
    expected = (("/api/v1/dashboard", "GET"), ("/api/v1/sessions", "GET"),
                ("/api/v1/sessions", "POST"), ("/api/v1/sessions/{session_id}", "GET"),
                ("/api/v1/sessions/{session_id}/simulate", "POST"),
                ("/api/v1/sessions/{session_id}/report.md", "GET"))
    for path, method in expected:
        assert method.lower() in paths[path]
        assert len([route for route in router.routes if route.path == path and method in route.methods]) == 1


def test_dataset_access_checks_ownership_and_domain():
    record = SimpleNamespace(owner_id="user-1", scenario="ecommerce")
    db = SimpleNamespace(get=lambda model, identifier: record)
    assert dataset_owned(db, user(), "data-1") is record
    record.owner_id = "other-user"
    with pytest.raises(HTTPException) as failure:
        dataset_owned(db, user(), "data-1")
    assert failure.value.status_code == 404
    record.owner_id = "user-1"
    record.scenario = "consumer"
    with pytest.raises(HTTPException) as failure:
        dataset_owned(db, user(), "data-1")
    assert failure.value.status_code == 403


def test_empty_dataset_id_is_invalid():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NewAnalysis(scenario="ecommerce", dataset_id="")


def test_comparison_checks_dataset_access_and_audits_result():
    db = FakeDB()
    scope = dict(baseline=['2026-10-01', '2026-10-01'], current=['2026-10-02', '2026-10-02'], filters={}, group_by='channel')
    def row(day, revenue):
        return dict(date=day, channel='自然流量', region='华东', category='服饰', segment='新客',
                    visitors='100', orders='5', revenue=revenue, material='0', logistics='0',
                    commission='0', other='0', tax='0', spend='0')
    dataset = SimpleNamespace(id="dataset-1", scenario="ecommerce", rows=[row('2026-10-01', '1000'), row('2026-10-02', '700')], digest="digest", owner_id="user-1")
    db.get = lambda model, identifier: dataset
    result = compare_dataset(dataset.id, Comparison(scope=scope, threshold="20"), db, user())
    assert result['status'] == 'anomaly'
    assert result['data_digest'] == 'digest'
    assert db.added[0].action == 'metric_compared'
    assert db.added[0].details['threshold'] == '20'
    assert db.commits == 1
    dataset.owner_id = 'someone-else'
    with pytest.raises(HTTPException) as failure:
        compare_dataset(dataset.id, Comparison(scope=scope, threshold="20"), db, user())
    assert failure.value.status_code == 404
    assert db.commits == 1


def test_metric_catalog_requires_domain_grant():
    assert metric_catalog('ecommerce', user())['scenario_metric']['metric'] == 'gmv_from_factors'
    with pytest.raises(HTTPException) as failure:
        metric_catalog('consumer', user())
    assert failure.value.status_code == 403


def test_baseline_variability_rejects_wrong_dataset_digest():
    from app.modules.analysis.api import get_baseline_variability
    record = SimpleNamespace(scenario='ecommerce', snapshot={'scope':{'baseline':['2026-10-01','2026-10-02']},
                               'dataset_version':'d1', 'data_digest':'expected'})
    dataset = SimpleNamespace(id='d1', scenario='ecommerce', digest='different')
    with patch('app.modules.analysis.api.owned', return_value=record), \
         patch('app.modules.analysis.api.dataset_owned', return_value=dataset):
        with pytest.raises(HTTPException) as error:
            get_baseline_variability('s1', FakeDB(), user())
    assert error.value.status_code == 409


def test_drilldown_export_is_authorized_audited_and_rejects_stale_scope():
    db = FakeDB()
    scope = {'baseline':['2026-10-01','2026-10-01'], 'current':['2026-10-02','2026-10-02'], 'filters':{}, 'group_by':'channel'}
    record = SimpleNamespace(id='session-1', snapshot={'dataset_version':'data-1', 'scope':scope, 'drilldown':[{'value':'自然流量'}]})
    revision = drilldown_revision(record.snapshot)
    with patch('app.modules.analysis.api.owned', return_value=record) as ownership:
        response = audit_drilldown_export('session-1', DrilldownExport(dataset_version='data-1', scope=scope, revision=revision), db, user())
        assert response.status_code == 204
        ownership.assert_called_once_with(db, user(), 'session-1')
        assert db.added[0].action == 'drilldown_export_requested'
        assert db.added[0].details['scope'] == scope
        with pytest.raises(HTTPException) as failure:
            audit_drilldown_export('session-1', DrilldownExport(dataset_version='old-data', scope=scope, revision=revision), db, user())
        assert failure.value.status_code == 409
        record.snapshot['drilldown'][0]['value'] = '付费投放'
        with pytest.raises(HTTPException) as failure:
            audit_drilldown_export('session-1', DrilldownExport(dataset_version='data-1', scope=scope, revision=revision), db, user())
        assert failure.value.status_code == 409
        assert db.commits == 1


def test_old_snapshot_gets_revision_without_mutating_stored_data():
    snapshot = {'dataset_version':'v1', 'scope':{'group_by':'channel'}, 'drilldown':[{'value':'自然流量'}]}
    result = serialize_session(SimpleNamespace(id='s1', snapshot=snapshot))
    assert result['drilldown_revision'] == drilldown_revision(snapshot)
    assert 'drilldown_revision' not in snapshot
    assert serialize_session(SimpleNamespace(id='s2', snapshot={'dataset_version':'fixed'}))['drilldown_revision'] is None


def test_serialized_evidence_status_tracks_check_without_mutating_snapshot():
    snapshot = {'evidence_status':'统计验证待执行', 'statistical_checks':[{'status':'computed'}]}
    view = serialize_session(SimpleNamespace(id='s1', snapshot=snapshot))
    assert '已执行每日均值检验' in view['evidence_status']
    assert '候选业务假设仍待验证' in view['evidence_status']
    assert snapshot['evidence_status'] == '统计验证待执行'
    snapshot['statistical_checks'] = [{'status':'not_applicable'}]
    assert '检验未能计算' in serialize_session(SimpleNamespace(id='s1', snapshot=snapshot))['evidence_status']


def test_report_labels_rule_candidates_as_unverified():
    db = FakeDB()
    snapshot = {'title':'测试', 'dataset_version':'v1', 'algorithm_version':'v1',
                'breakdown':{'baseline':'1','current':'2','delta':'1','unit':'元','factors':[]},
                'limitations':['不能证明因果'], 'hypotheses':[{'question':'是否存在差异？',
                'status_label':'待验证', 'factor_label':'访问次数', 'evidence':[
                    {'kind':'descriptive_comparison','dimension':'channel','metric':'访问次数','unit':'次',
                     'delta_unit':'次','groups':[{'value':'A|<script>','baseline':'100','current':None,'delta':None}],
                     'total_groups':21,'truncated':True,'note':'分母为零时不计算。'}]}]}
    with patch('app.modules.analysis.api.owned', return_value=SimpleNamespace(id='s1', snapshot=snapshot)):
        response = markdown_report('s1', db, user())
    body = response.body.decode('utf-8')
    assert '规则候选问题，尚未执行统计验证' in body
    assert '### 是否存在差异？' in body
    assert '状态：待验证' in body
    assert r'A\|&lt;script&gt;' in body
    assert '不适用' in body
    assert '仅展示 1 / 21 个分组' in body
    assert db.added[0].action == 'report_exported'


def test_candidate_report_links_only_matching_factor_and_keeps_pending_status():
    from app.modules.analysis.report import hypothesis_sections
    candidates=[{'question':'渠道差异？','status_label':'待验证','factor_label':'转化','factor_key':'conversion','evidence':[]},
                {'question':'旧问题？','status_label':'待验证','factor_label':'旧因子','evidence':[]}]
    checks=[{'factor_key':'conversion','metric':'渠道 A | B','status':'computed'},
            {'factor_key':'basket','metric':'不相关','status':'computed'},
            {'metric':'旧整体检验','status':'computed'},
            {'factor_key':'conversion','metric':'渠道 C','status':'not_applicable','reason':'分母为零'}]
    report='\n'.join(hypothesis_sections(candidates,checks))
    assert r'渠道 A \| B：已计算' in report
    assert '渠道 C：无法计算：分母为零' in report
    assert '不相关' not in report and '旧整体检验' not in report
    assert report.count('状态：待验证')==2 and '不直接验证此问题' in report


def test_simulation_comparison_persists_atomically_and_detects_stale_analysis():
    from app.domain.scenarios import calculate
    db = FakeDB()
    record = SimpleNamespace(id='s1', scenario='ecommerce', snapshot=calculate('ecommerce'))
    revision = analysis_revision(record.snapshot)
    options = [SimulationScenario(name='小幅',changes={'conversion':'0.035'}),
               SimulationScenario(name='较大',changes={'conversion':'0.04'})]
    with patch('app.modules.analysis.service.owned', return_value=record) as ownership:
        result = service.compare_simulations(db, user(), 's1', revision, draft_revision(record.snapshot, 'simulation_scenarios'), options)
        ownership.assert_called_once_with(db, user(), 's1', lock=True)
        assert [float(item['improvement']) for item in result['simulation_scenarios']] == [108000,216000]
        assert all(item['interval'] is None for item in result['simulation_scenarios'])
        assert result['analysis_revision'] == revision
        assert db.added[0].action == 'simulation_comparison_saved'
        assert db.commits == 1
        old_results = record.snapshot['simulation_scenarios']
        with pytest.raises(HTTPException) as failure:
            service.compare_simulations(db, user(), 's1', revision, draft_revision(record.snapshot, 'simulation_scenarios'), [options[0],SimulationScenario(name='错误',changes={'conversion':'2'})])
        assert failure.value.status_code == 422
        assert record.snapshot['simulation_scenarios'] is old_results
        record.snapshot = {**record.snapshot, 'algorithm_version':'changed'}
        with pytest.raises(HTTPException) as failure:
            service.compare_simulations(db, user(), 's1', revision, draft_revision(record.snapshot, 'simulation_scenarios'), options)
        assert failure.value.status_code == 409
        with pytest.raises(HTTPException) as failure:
            service.compare_simulations(db, user('manager'), 's1', analysis_revision(record.snapshot), draft_revision(record.snapshot, 'simulation_scenarios'), options)
        assert failure.value.status_code == 403
        assert db.commits == 1


def test_multifactor_scenarios_preserve_every_parameter_and_calculate_jointly():
    from app.domain.scenarios import calculate
    db = FakeDB()
    record = SimpleNamespace(id='s1', scenario='ecommerce', snapshot=calculate('ecommerce'))
    choice = SimulationScenario(name='转化与客单价', changes={'conversion':'0.04', 'basket':'200'})
    with patch('app.modules.analysis.service.owned', return_value=record):
        result = service.compare_simulations(db, user(), 's1', analysis_revision(record.snapshot),
                                             draft_revision(record.snapshot, 'simulation_scenarios'), [choice])
    item = result['simulation_scenarios'][0]
    assert item['changes'] == {'conversion':'0.04', 'basket':'200'}
    assert float(item['prediction']) == 960000
    assert float(item['improvement']) == 312000
    assert item['interval'] is None and '未估计因子联动' in item['assumptions']


def test_preview_uses_same_math_without_saving_and_rejects_stale_or_unauthorized():
    from copy import deepcopy
    from app.domain.scenarios import calculate
    db = FakeDB()
    record = SimpleNamespace(id='s1', scenario='ecommerce', snapshot=calculate('ecommerce'))
    original = deepcopy(record.snapshot)
    options = [SimulationScenario(name='测试', changes={'conversion':'0.04', 'basket':'200'})]
    with patch('app.modules.analysis.service.owned', return_value=record):
        preview = service.preview_simulations(db, user(), 's1', analysis_revision(record.snapshot), options)
        assert float(preview[0]['prediction']) == 960000
        assert record.snapshot == original and not db.added and db.commits == 0
        with pytest.raises(HTTPException) as stale:
            service.preview_simulations(db, user(), 's1', '0'*64, options)
        assert stale.value.status_code == 409
        with pytest.raises(HTTPException) as denied:
            service.preview_simulations(db, user('manager'), 's1', analysis_revision(record.snapshot), options)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as invalid:
            service.preview_simulations(db, user(), 's1', analysis_revision(record.snapshot),
                                        [SimulationScenario(name='错误', changes={'conversion':'2'})])
        assert invalid.value.status_code == 422
        assert record.snapshot == original and not db.added and db.commits == 0


def test_report_contains_saved_simulations_with_assumptions():
    from app.domain.scenarios import calculate
    db=FakeDB()
    snapshot=calculate('ecommerce')
    snapshot['simulation_scenarios']=[{'name':'A|<script>', 'changes':{'conversion':'0.035'},
                                        'prediction':'756000', 'improvement':'108000'}]
    with patch('app.modules.analysis.api.owned', return_value=SimpleNamespace(id='s1', snapshot=snapshot)):
        report=markdown_report('s1',db,user()).body.decode('utf-8')
    assert r'A\|&lt;script&gt;' in report
    assert '订单转化因子 = 0.035' in report
    assert '756000' in report and '108000' in report
    assert '收益区间暂无依据' in report


def test_action_list_preserves_other_drafts_and_rejects_unfounded_benefit():
    from app.domain.scenarios import calculate
    db=FakeDB()
    snapshot=calculate('ecommerce')
    snapshot['simulation_scenarios']=[{'name':'已有情景'}]
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=snapshot)
    revision=analysis_revision(snapshot)
    item=ActionItem(action='  检查渠道投放  ',factor_key='visitors')
    with patch('app.modules.analysis.service.owned',return_value=record):
        result=service.save_action_items(db,user(),'s1',revision,draft_revision(record.snapshot, 'action_items'),[item])
        assert result['analysis_revision']==revision
        assert result['simulation_scenarios']==[{'name':'已有情景'}]
        assert result['action_items'][0]['action']=='检查渠道投放'
        assert result['action_items'][0]['factor_contribution']==snapshot['breakdown']['factors'][0]['contribution']
        assert result['action_items'][0]['estimated_benefit'] is None
        assert db.added[0].action=='action_items_saved'
        before=record.snapshot
        with pytest.raises(HTTPException) as failure:
            service.save_action_items(db,user(),'s1',revision,draft_revision(record.snapshot, 'action_items'),[ActionItem(action='检查',factor_key='visitors',estimated_benefit='100')])
        assert failure.value.status_code==422
        assert record.snapshot is before and db.commits==1
        with pytest.raises(HTTPException) as failure:
            service.save_action_items(db,user('manager'),'s1',revision,draft_revision(record.snapshot, 'action_items'),[])
        assert failure.value.status_code==403
        with pytest.raises(HTTPException) as failure:
            service.save_action_items(db,user(),'s1','0'*64,draft_revision(record.snapshot, 'action_items'),[])
        assert failure.value.status_code==409


def test_action_report_marks_missing_and_user_entered_estimates():
    from app.modules.analysis.report import action_section
    base={'action':'检查 | <script>', 'factor_label':'访问次数','factor_contribution':'-10',
          'owner_role':'','estimated_days':None,'estimated_benefit':None,'benefit_basis':''}
    report='\n'.join(action_section([base,dict(base,estimated_benefit='120',benefit_basis='业务估算'),
                                     dict(base,benefit_basis='等待渠道数据')]))
    assert r'检查 \| &lt;script&gt;' in report
    assert '待补充' in report and '暂无依据' in report
    assert '120 元；业务估算（分析师估计）' in report
    assert '暂无金额；等待渠道数据' in report


def test_report_note_is_versioned_authorized_and_exported():
    from io import BytesIO
    from openpyxl import load_workbook
    from app.domain.scenarios import calculate
    from app.modules.analysis.api import ReportNote, save_report_note
    from app.modules.analysis.snapshot import report_revision
    from app.modules.analysis.report import markdown_report_text
    from app.modules.analysis.exporters import spreadsheet
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ReportNote(revision='0'*64,text='不可保存\x00')
    snapshot=calculate('ecommerce')
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=snapshot)
    db=FakeDB()
    analyst=user(); analyst.username='analyst'
    revision=report_revision(snapshot)
    with patch('app.modules.analysis.api.owned',return_value=record):
        result=save_report_note('s1',ReportNote(revision=revision,text='  =检查 | <script>  '),db,analyst)
        assert result['analysis_revision']==analysis_revision(snapshot)
        assert result['report_note']['text']=='=检查 | <script>'
        assert db.added[0].action=='report_note_saved'
        with pytest.raises(HTTPException) as stale:
            save_report_note('s1',ReportNote(revision=revision,text='旧说明'),db,analyst)
        assert stale.value.status_code==409
        with pytest.raises(HTTPException) as denied:
            save_report_note('s1',ReportNote(revision=result['report_revision'],text='无权限'),db,user('manager'))
        assert denied.value.status_code==403
        markdown=markdown_report_text(record.snapshot)
        assert r'=检查 \| &lt;script&gt;' in markdown
        sheet=load_workbook(BytesIO(spreadsheet(record.snapshot)),data_only=False)['概要']
        cells={row[0].value:row[1] for row in sheet.iter_rows(min_row=2)}
        assert cells['分析师说明'].value=='=检查 | <script>'
        assert cells['分析师说明'].data_type=='s'
        cleared=save_report_note('s1',ReportNote(revision=result['report_revision'],text='  '),db,analyst)
        assert cleared['report_note'] is None


def test_report_preview_checks_revision_and_keeps_untrusted_text_escaped():
    from app.domain.scenarios import calculate
    from app.modules.analysis.api import report_preview
    from app.modules.analysis.snapshot import report_revision
    snapshot=calculate('ecommerce')
    snapshot['report_note']={'text':'<script>alert(1)</script>','author':'analyst','updated_at':'2026-11-25T00:00:00Z'}
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=snapshot)
    db=FakeDB()
    with patch('app.modules.analysis.api.owned',return_value=record) as ownership:
        with pytest.raises(HTTPException) as stale:
            report_preview('s1',db,user(),revision='0'*64)
        assert stale.value.status_code==409 and db.commits==0
        revision=report_revision(snapshot)
        preview=report_preview('s1',db,user(),revision=revision)
        ownership.assert_called_with(db, user(), 's1')
        assert preview['revision']==revision and '&lt;script&gt;' in preview['markdown']
        assert '<script>' not in preview['markdown']
        assert db.added[0].action=='report_previewed' and db.commits==1


def test_report_user_text_cannot_create_markdown_headings_or_lists():
    from app.modules.analysis.report import _cell
    assert _cell('# 伪造标题') == r'\# 伪造标题'
    assert _cell('- 伪造列表') == r'\- 伪造列表'
    assert _cell('+ 伪造列表') == r'\+ 伪造列表'


def test_action_validation_rejects_nonfinite_amount_unknown_factor_and_blank_action():
    from pydantic import ValidationError
    from app.domain.scenarios import calculate
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=calculate('ecommerce'))
    revision=analysis_revision(record.snapshot)
    db=FakeDB()
    with pytest.raises(ValidationError):
        ActionItem(action='  ',factor_key='visitors')
    with patch('app.modules.analysis.service.owned',return_value=record):
        for item in (ActionItem(action='检查',factor_key='unknown'),
                     ActionItem(action='检查',factor_key='visitors',estimated_benefit='NaN',benefit_basis='估算')):
            with pytest.raises(HTTPException) as failure:
                service.save_action_items(db,user(),'s1',revision,draft_revision(record.snapshot, 'action_items'),[item])
            assert failure.value.status_code==422
    assert db.commits==0


def test_parallel_draft_edits_detect_conflicts_without_blocking_other_draft():
    from app.domain.scenarios import calculate
    db=FakeDB()
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=calculate('ecommerce'))
    revision=analysis_revision(record.snapshot)
    old_actions=draft_revision(record.snapshot,'action_items')
    old_simulations=draft_revision(record.snapshot,'simulation_scenarios')
    first=ActionItem(action='检查渠道',factor_key='visitors')
    second=ActionItem(action='调整活动',factor_key='conversion')
    simulation=SimulationScenario(name='情景',changes={'conversion':'0.04'})
    with patch('app.modules.analysis.service.owned',return_value=record):
        action_result=service.save_action_items(db,user(),'s1',revision,old_actions,[first])
        assert action_result['action_revision'] != old_actions
        with pytest.raises(HTTPException) as failure:
            service.save_action_items(db,user(),'s1',revision,old_actions,[second])
        assert failure.value.status_code==409
        assert record.snapshot['action_items'][0]['action']=='检查渠道'
        # An action edit doesn't invalidate a different simulation draft.
        simulation_result=service.compare_simulations(db,user(),'s1',revision,old_simulations,[simulation])
        assert simulation_result['action_items'][0]['action']=='检查渠道'
        assert simulation_result['simulation_revision'] != old_simulations
        with pytest.raises(HTTPException) as failure:
            service.compare_simulations(db,user(),'s1',revision,old_simulations,[simulation])
        assert failure.value.status_code==409
        assert db.commits==2


def test_draft_revisions_are_available_for_old_snapshots_and_separate_by_kind():
    snapshot={'dataset_version':'legacy'}
    view=serialize_session(SimpleNamespace(id='s1',snapshot=snapshot))
    assert len(view['action_revision'])==64
    assert len(view['simulation_revision'])==64
    assert view['action_revision'] != view['simulation_revision']
    assert draft_revision(snapshot,'action_items') == draft_revision({'action_items':[]},'action_items')


def test_daily_check_persists_with_data_version_and_rejects_stale_changes():
    from app.domain.exploration import analyze
    rows=[dict(date=f'2026-10-{i:02}',channel='自然流量',region='华东',category='服饰',segment='新客',
               visitors='1',orders='1',revenue=str(i),material='0',logistics='0',commission='0',other='0',tax='0',spend='0') for i in range(1,7)]
    scope={'baseline':['2026-10-01','2026-10-03'],'current':['2026-10-04','2026-10-06'], 'filters':{},'group_by':'channel'}
    snapshot=analyze('ecommerce',rows,scope,'dataset-1')
    snapshot['data_digest']='digest'
    snapshot['action_items']=[{'action':'保留'}]
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=snapshot)
    dataset=SimpleNamespace(id='dataset-1',scenario='ecommerce',rows=rows,digest='digest')
    db=FakeDB(); revision=analysis_revision(snapshot); old=draft_revision(snapshot,'statistical_checks')
    with patch('app.modules.analysis.service.owned',return_value=record),patch('app.modules.analysis.service.dataset_owned',return_value=dataset):
        result=service.run_daily_check(db,user(),'s1',revision,old,0.95)
        check=result['statistical_checks'][0]
        assert check['status']=='computed' and check['dataset_version']=='dataset-1' and check['data_digest']=='digest'
        assert result['action_items']==[{'action':'保留'}]
        assert result['analysis_revision']==revision
        with pytest.raises(HTTPException) as failure:
            service.run_daily_check(db,user(),'s1',revision,old,0.95)
        assert failure.value.status_code==409
        candidate=service.run_daily_check(db,user(),'s1',revision,result['statistics_revision'],0.95,'basket')
        assert len(candidate['statistical_checks'])==2
        selected=candidate['statistical_checks'][-1]
        assert selected['factor_key']=='basket' and selected['status']=='computed'
        assert '不检验分组集中程度' in '\n'.join(selected['limitations'])
        assert selected['method_version']=='daily-welch-v5'
        assert selected['calculated_at'].endswith('+00:00')
        assert selected['scipy_version']
        from app.modules.analysis.report import statistical_section
        rendered='\n'.join(statistical_section(candidate['statistical_checks']))
        assert 'dataset-1' in rendered and 'digest' in rendered and '2026-10-01' in rendered
        assert 'daily-welch-v5' in rendered and 'basket' in rendered
        assert db.added[-1].details['factor_key']=='basket'
        repeated=service.run_daily_check(db,user(),'s1',revision,candidate['statistics_revision'],0.90,'basket')
        assert len(repeated['statistical_checks'])==2
        assert repeated['statistical_checks'][-1]['confidence_level']==0.90
        dataset.digest='different'
        with pytest.raises(HTTPException) as failure:
            service.run_daily_check(db,user(),'s1',revision,repeated['statistics_revision'],0.95)
        assert failure.value.status_code==409
    assert db.commits==3


def test_pdf_and_spreadsheet_are_authorized_and_spreadsheet_values_are_literal():
    from io import BytesIO
    from openpyxl import load_workbook
    from app.domain.scenarios import calculate
    snapshot=calculate('ecommerce')
    snapshot['action_items']=[{'action':'=1+1','factor_label':'访问次数','factor_contribution':'123.4567890123456789',
                               'owner_role':'','estimated_days':None,'estimated_benefit':None,'benefit_basis':''}]
    record=SimpleNamespace(id='s1',snapshot=snapshot)
    db=FakeDB()
    with patch('app.modules.analysis.api.owned',return_value=record) as ownership:
        xlsx=spreadsheet_report('s1',db,user())
        output=pdf_report('s1',db,user())
    assert ownership.call_count==2
    assert output.body.startswith(b'%PDF-')
    assert xlsx.media_type=='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    workbook=load_workbook(BytesIO(xlsx.body),data_only=False)
    assert workbook['行动清单']['A2'].value=='=1+1'
    assert workbook['行动清单']['A2'].data_type=='s'
    assert workbook['行动清单']['C2'].value=='123.4567890123456789'
    assert workbook['概要']['A2'].value=='状态'
    assert [event.details['format'] for event in db.added]==['xlsx','pdf']
    assert db.commits==2


def test_pdf_reports_missing_font_without_marking_exported():
    from app.domain.scenarios import calculate
    db=FakeDB()
    record=SimpleNamespace(id='s1',snapshot=calculate('ecommerce'))
    with patch('app.modules.analysis.api.owned',return_value=record), patch('app.modules.analysis.api.pdf',side_effect=RuntimeError('PDF 中文字体不可用')):
        with pytest.raises(HTTPException) as failure:
            pdf_report('s1',db,user())
    assert failure.value.status_code==503
    assert db.commits==0 and not db.added


def test_report_matches_live_events_with_owner_scope_and_preserves_limitations():
    from io import BytesIO
    from openpyxl import load_workbook
    from app.domain.scenarios import calculate
    snapshot=calculate('ecommerce')
    snapshot['scope']={'baseline':['2026-09-01','2026-09-02'], 'current':['2026-10-03','2026-10-04'],
                       'filters':{'region':'华东'},'group_by':'channel'}
    snapshot['data_digest']='digest'
    record=SimpleNamespace(id='s1',scenario='ecommerce',snapshot=snapshot)
    relevant=SimpleNamespace(id='event-1',scenario='ecommerce',title='活动|<script>',start='2026-10-01',
                             end='2026-10-01',scope={'region':['华东']},source='业务日历')
    mismatch=SimpleNamespace(id='event-2',scenario='ecommerce',title='其他区域',start='2026-10-01',
                             end='2026-10-01',scope={'region':['华南']},source='业务日历')
    db=FakeDB()
    statements=[]
    def scalars(statement):
        statements.append(statement)
        return iter([relevant,mismatch])
    db.scalars=scalars
    with patch('app.modules.analysis.api.owned',return_value=record):
        markdown=markdown_report('s1',db,user()).body.decode('utf-8')
        xlsx=spreadsheet_report('s1',db,user())
        pdf_bytes=pdf_report('s1',db,user()).body
    assert r'活动\|&lt;script&gt;' in markdown
    assert '其他区域' not in markdown
    assert '不证明因果' in markdown and '每次导出重新匹配' in markdown
    assert '事件结束距现期开始 2 天' in markdown and '事件范围包含该值' in markdown
    assert '当前公式局部敏感性' in markdown and '不是历史估计' in markdown
    workbook=load_workbook(BytesIO(xlsx.body),data_only=False)
    assert workbook['事件关联']['B3'].value=='活动|<script>'
    assert '事件结束距现期开始 2 天' in workbook['事件关联']['G3'].value
    assert workbook['事件关联']['H3'].value=='候选关联，尚不能证明因果'
    assert workbook['公式敏感性']['A3'].value == '访问次数'
    assert pdf_bytes.startswith(b'%PDF-')
    for query in statements:
        params=query.compile().params
        assert 'user-1' in params.values() and 'ecommerce' in params.values()
    assert all(event.details['event_count']==1 for event in db.added)
    assert 'report_events' not in snapshot
