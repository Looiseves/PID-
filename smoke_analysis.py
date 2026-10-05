import copy
from unittest.mock import patch
from PySide6.QtTest import QTest
from integration import analysis_identity, write_proposal
from workspace_ui import preview_analysis, api_result, stage_proposal, ApiWorker


def run_analysis(app,w,folder,check):
    w.navigation.navigate('ai')
    with patch('workspace_ui.request_analysis') as request:
        QTest.mouseClick(w.ai_preview,__import__('PySide6').QtCore.Qt.MouseButton.LeftButton)
        app.processEvents()
        dialog=w.analysis_preview
        check('analysis_preview_is_readonly_and_makes_no_request',dialog.isVisible() and dialog.context_text.isReadOnly() and not request.called)
        check('analysis_preview_shows_actual_scope_without_api_key','analysis_window' in dialog.context_text.toPlainText() and 'api_key' not in dialog.context_text.toPlainText())
        dialog.grab().save(str(folder/'analysis-context.png'))
        dialog.close()
    context={'parameters':{'kp':2}}
    worker=ApiWorker({},'',context,'',w)
    context['parameters']['kp']=9
    check('analysis_worker_keeps_independent_click_snapshot',worker.context['parameters']['kp']==2)
    w.api_reference=(w.experiment,analysis_identity(w.experiment))
    w.experiment.params['kp']+=.1
    api_result(w,'旧数据建议',{})
    check('analysis_old_result_warns_after_parameter_change','旧实验' in w.ai_status.text())
    w.api_reference=(w.experiment,analysis_identity(w.experiment))
    api_result(w,'当前建议',{})
    check('analysis_current_result_remains_review_only','未应用' in w.ai_status.text())
    w.publish_bridge()
    write_proposal(w.bridge.directory,{'kp':1.6},'只改变 P 验证波动')
    w.pending_proposal=w.bridge.take_proposal()
    original=w.spins['kp'].value()
    w.experiment.params['kp']+=.1
    stage_proposal(w)
    check('mcp_staging_rejects_proposal_changed_after_receipt',w.spins['kp'].value()==original and w.pending_proposal is None and '过期' in w.proposal_label.text())
