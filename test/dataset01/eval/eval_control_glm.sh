#!/usr/bin/env bash
# glm-5.3-flash 对照臂（--no-agent-tools）：同模型分离工具净贡献；收敛至 600 ok → 标记
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
for i in 1 2 3 4 5 6; do
    $PY longbench_agent_eval.py --no-agent-tools --out longbench_agent_control_glm_results.json >> $R/v3_agent_control_glm2.log 2>&1
    N=$(wc -l < $R/longbench_agent_control_glm_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain11] control-glm pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done
date > $R/EVAL_CONTROL_GLM_DONE
echo "[chain11] ALL DONE" >> $R/eval_agent_chain.log
