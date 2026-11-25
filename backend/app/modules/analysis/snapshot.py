"""Stable identifiers for the exact analysis table being viewed."""
import hashlib
import json


def _revision(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def report_revision(snapshot):
    return _revision(snapshot)


def draft_revision(snapshot, name):
    if name not in {'simulation_scenarios', 'action_items', 'statistical_checks', 'report_note'}:
        raise ValueError('未知草稿类型')
    return _revision({'kind': name, 'items': snapshot.get(name, [])})


def analysis_revision(snapshot):
    # User-authored scenario and action drafts do not change the analysis itself.
    content = {key: value for key, value in snapshot.items() if key not in {'simulation_scenarios', 'action_items', 'statistical_checks', 'report_note'}}
    return _revision(content)


def drilldown_revision(snapshot):
    if not snapshot.get('drilldown'):
        return None
    content = {'dataset_version': snapshot.get('dataset_version'),
               'scope': snapshot.get('scope'), 'drilldown': snapshot['drilldown']}
    return _revision(content)


def serialize_session(record):
    checks = record.snapshot.get('statistical_checks') or []
    status = record.snapshot.get('evidence_status')
    if checks:
        computed = any(check.get('status') == 'computed' for check in checks)
        unavailable = any(check.get('status') != 'computed' for check in checks)
        if computed and unavailable:
            status = '数学分解已完成，已执行每日均值检验；部分检验未能计算，候选业务假设仍待验证。'
        elif computed:
            status = '数学分解已完成，已执行每日均值检验；候选业务假设仍待验证。'
        else:
            status = '数学分解已完成；每日均值检验未能计算，候选业务假设仍待验证。'
    return {'id': record.id, **record.snapshot, 'evidence_status':status,
            'drilldown_revision': drilldown_revision(record.snapshot),
            'analysis_revision': analysis_revision(record.snapshot),
            'action_revision': draft_revision(record.snapshot, 'action_items'),
            'simulation_revision': draft_revision(record.snapshot, 'simulation_scenarios'),
            'statistics_revision': draft_revision(record.snapshot, 'statistical_checks'),
            'note_revision': draft_revision(record.snapshot, 'report_note'),
            'report_revision': _revision(record.snapshot)}
