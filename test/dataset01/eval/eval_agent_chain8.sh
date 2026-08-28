#!/usr/bin/env bash
# glm-5.3-flash 双臂：对照臂（关工具）→ 工具臂，各收敛至 600 ok → 标记
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
for i in 1 2 3 4; do
    $PY longbench_agent_eval.py --no-agent-tools --out longbench_agent_control_results.json >> $R/v3_agent_control_glm.log 2>&1
    N=$(wc -l < $R/longbench_agent_control_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain8] control pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done
for i in 1 2 3 4; do
    $PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools_glm.log 2>&1
    N=$(wc -l < $R/longbench_agent_tools_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain8] tools pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done
date > $R/EVAL_AGENT_DONE
echo "[chain8] ALL DONE" >> $R/eval_agent_chain.log
