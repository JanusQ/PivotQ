from ..models import StageDefinition, StagePlan, TaskDefinition, WorkflowPlan
from ..stage_hardware import stage_policy

TASK = TaskDefinition('quantum-circuit','1.0','量子电路实验','编辑门序列，通过融合框架在所选设备上执行。',{
    'type':'object','properties':{
        'shots':{'type':'integer','title':'采样次数','default':1024,'minimum':1,'maximum':100000},
        'seed':{'type':'integer','title':'采样种子','default':42,'minimum':0,'maximum':4294967295},
    }}, (StageDefinition('circuit_execution','电路执行','按目标硬件执行电路；Simulation 模式使用 CPU 状态向量与采样','gpu',('gpu',)),))

def validate_and_plan(request, *, prediction=False):
    values = request.get('inputs') or {}
    errors, normalized = [], {}
    for key, schema in TASK.input_schema['properties'].items():
        value = values.get(key,schema['default'])
        if type(value) is not int or not schema['minimum'] <= value <= schema['maximum']:
            errors.append({'path':'inputs.'+key,'message':'整数参数超出支持范围'})
        normalized[key] = value
    if set(values) - set(normalized):
        errors.append({'path':'inputs','message':'存在未知参数'})
    default, allowed = stage_policy(TASK.stages[0], prediction=prediction)
    device = request.get('hardware',{}).get('circuit_execution', default)
    if device not in allowed:
        errors.append({'path':'hardware','message':f'当前电路执行模式支持 {", ".join(allowed)}'})
    if set(request.get('hardware', {})) - {'circuit_execution'}:
        errors.append({'path': 'hardware', 'message': '存在未知执行阶段'})
    stage = StagePlan('circuit_execution','电路执行',device,(),{device:1},request.get('hardware_targets',{}).get('circuit_execution'),request.get('target_snapshots',{}).get('circuit_execution'))
    return errors, None if errors else WorkflowPlan(TASK.id,TASK.version,normalized,(stage,))
