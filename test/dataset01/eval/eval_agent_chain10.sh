#!/usr/bin/env bash
# 修复 chunk_read 后的工具臂复测：收敛至 600 ok → 标记；对照臂沿用 mimo 34.5%，
# 修复前工具臂基线已归档（longbench_agent_tools_prefix_results.json，66.9%）
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
for i in 1 2 3 4 5 6; do
    $PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools_v2.log 2>&1
    N=$(wc -l < $R/longbench_agent_tools_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain10] tools pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done
date > $R/EVAL_AGENT_DONE_V2
echo "[chain10] ALL DONE" >> $R/eval_agent_chain.log
